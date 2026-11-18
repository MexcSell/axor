// Same-origin JSON GET with AXoR's session cookie; a 401/403 is SignedOut so pages can say so.
export class SignedOut extends Error {}
export class Forbidden extends Error {}

export async function getJSON<T>(url: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(url, { credentials: "same-origin", signal });
  if (r.status === 401) throw new SignedOut("Sign in to AXoR first.");
  if (r.status === 403) throw new Forbidden("Only administrators can see this.");
  if (!r.ok) throw new Error(`The server answered ${r.status}.`);
  return (await r.json()) as T;
}
