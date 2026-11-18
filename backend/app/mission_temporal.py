"""Temporal as the durable runtime under Mission Control (5.1: the spec's "Temporal for durable mission execution").

Off unless MISSIONS_RUNTIME=temporal. Then every time Mission Control hands a mission to its worker (missions._submit), it starts
the Temporal workflow "AxorMission" with the workflow id axor-mission-<id> instead. The workflow runs one activity,
"axor_advance_mission", which is missions._advance(mid): the same stage machine (understand → … → learn) as before, now with
Temporal's history, retries and visibility around it. The activity heartbeats every HEARTBEAT seconds, so when the server
dies mid-stage Temporal hands the activity to the next worker after HEARTBEAT_TIMEOUT instead of waiting out the whole stage.

What stays the same: the stage state lives in mx_missions (Postgres or SQLite); the lease (missions._claim) still stops a stage
running twice; the missions clock still watches budgets, deadlines and child work. If Temporal can't be reached, submit()
returns False and the mission runs on the in-process pool exactly as without Temporal (logged, never lost).

  MISSIONS_RUNTIME=temporal
  TEMPORAL_ADDRESS=temporal-frontend.axor.svc.cluster.local:7233   (k8s/stack/temporal.yaml; default localhost:7233)
  TEMPORAL_NAMESPACE=default
  TEMPORAL_TASK_QUEUE=axor-missions

The worker runs inside the web process (one event loop on its own thread), so one AXoR server = one worker. temporalio is in
requirements.txt from 5.1; without it (an older image) this module reports "not installed" and Mission Control runs as before.
"""
import asyncio, atexit, concurrent.futures, contextvars, logging, os, threading, time
from datetime import timedelta

log = logging.getLogger("mission_temporal")

ENABLED = os.getenv("MISSIONS_RUNTIME", "").lower() == "temporal"
ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "axor-missions")
WORKFLOW, ACTIVITY = "AxorMission", "axor_advance_mission"
STAGE_TIMEOUT = timedelta(hours=float(os.getenv("TEMPORAL_STAGE_HOURS", "6")))
HEARTBEAT, HEARTBEAT_TIMEOUT = 20, timedelta(seconds=90)
CONNECT_TIMEOUT = 10


def installed():
    return _workflow is not None


try:  # the workflow class has to live at module level (Temporal refuses local classes)
    from temporalio import activity as _activity, workflow as _workflow
    from temporalio.common import RetryPolicy as _RetryPolicy
except ImportError:  # not installed: ENABLED does nothing (start() says so)
    _workflow = None

if _workflow is not None:
    @_workflow.defn(name=WORKFLOW, sandboxed=False)
    class AxorMission:
        """One mission's stages from where it stands until it waits, pauses or is delivered (missions._advance)."""
        @_workflow.run
        async def run(self, mid: int) -> str:
            return await _workflow.execute_activity(
                ACTIVITY, mid, start_to_close_timeout=STAGE_TIMEOUT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=_RetryPolicy(initial_interval=timedelta(seconds=15), backoff_coefficient=2.0, maximum_attempts=5))


def _make_activity(advance):
    @_activity.defn(name=ACTIVITY)
    def advance_mission(mid: int) -> str:
        done = threading.Event()
        ctx = contextvars.copy_context()  # heartbeat() needs the activity's context: the beating thread gets a copy

        def beat():
            while not done.wait(HEARTBEAT):
                try: ctx.run(_activity.heartbeat)
                except Exception: return  # noqa: BLE001 - the activity is finishing or was cancelled
        threading.Thread(target=beat, daemon=True, name=f"temporal-beat-{mid}").start()
        try:
            advance(mid)
            return "advanced"
        finally:
            done.set()
    return advance_mission


class Runtime:
    """One Temporal client + worker for this server, on an event loop in its own thread."""

    def __init__(self, advance):
        self.advance = advance
        self.loop = None
        self.client = None
        self.error = None
        self.started = None
        self.submitted = self.fallbacks = 0
        self._ready = threading.Event()
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=int(os.getenv("TEMPORAL_ACTIVITY_THREADS", "8")),
                                                          thread_name_prefix="temporal-activity")
        self._thread = threading.Thread(target=self._run, daemon=True, name="temporal-worker")
        self._thread.start()
        self._ready.wait(CONNECT_TIMEOUT + 2)
        atexit.register(self.close)

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            log.warning("temporal runtime stopped: %s (missions run on the in-process pool)", self.error)
        finally:
            self._ready.set()

    async def _main(self):
        from temporalio.client import Client
        from temporalio.worker import Worker
        self.client = await asyncio.wait_for(Client.connect(ADDRESS, namespace=NAMESPACE), CONNECT_TIMEOUT)
        worker = Worker(self.client, task_queue=QUEUE, workflows=[AxorMission], activities=[_make_activity(self.advance)],
                        activity_executor=self._pool, max_concurrent_activities=self._pool._max_workers)
        self.started = time.time()
        self._worker = worker
        log.info("temporal: worker on %s/%s queue %s", ADDRESS, NAMESPACE, QUEUE)
        self._ready.set()
        await worker.run()

    def close(self, timeout=5):
        """Stop the worker cleanly (at exit: a daemon thread killed inside Temporal's core aborts the process)."""
        w, loop = getattr(self, "_worker", None), self.loop
        if w is None or loop is None or not loop.is_running(): return
        try: asyncio.run_coroutine_threadsafe(w.shutdown(), loop).result(timeout)
        except Exception: pass  # noqa: BLE001

    @property
    def ready(self):
        return self.client is not None and self.error is None and self.loop is not None and self.loop.is_running()

    def submit(self, mid):
        """True when the mission's next stages now run as a Temporal workflow; False = run it in-process (Temporal down)."""
        if not self.ready:
            self.fallbacks += 1
            return False
        from temporalio.exceptions import WorkflowAlreadyStartedError

        async def start():
            try:
                await self.client.start_workflow(WORKFLOW, mid, id=f"axor-mission-{mid}", task_queue=QUEUE)
            except WorkflowAlreadyStartedError:
                pass  # its workflow is already running: the activity will pick up from the mission's stage
        try:
            asyncio.run_coroutine_threadsafe(start(), self.loop).result(CONNECT_TIMEOUT)
            self.submitted += 1
            return True
        except Exception as e:  # noqa: BLE001
            self.fallbacks += 1
            log.warning("temporal: couldn't start mission %s (%s): running it in-process", mid, e)
            return False

    def status(self):
        return {"enabled": True, "installed": True, "ready": self.ready, "address": ADDRESS, "namespace": NAMESPACE, "queue": QUEUE,
                "error": self.error, "since": self.started, "submitted": self.submitted, "fallbacks": self.fallbacks}


def start(advance):
    """A Runtime when MISSIONS_RUNTIME=temporal and temporalio is installed, else None (Mission Control runs in-process)."""
    if not ENABLED: return None
    if not installed():
        log.warning("MISSIONS_RUNTIME=temporal but temporalio isn't installed: missions run in-process")
        return None
    global CURRENT
    CURRENT = Runtime(advance)
    return CURRENT


CURRENT = None  # this server's Runtime, for the status page


def status(rt=None):
    rt = rt or CURRENT
    if rt is not None: return rt.status()
    return {"enabled": ENABLED, "installed": installed(), "ready": False, "address": ADDRESS if ENABLED else None,
            "error": ("temporalio isn't installed in this image" if ENABLED and not installed() else None)}
