"""risk.py: the flags that put subnets on Avoid & Caution and mark scam signals."""
import unittest

from app import risk


def subnet(**kw):
    r = {"name": "Good subnet", "task": "Text generation", "conditions": "", "description": "Serves a model",
         "links": {"github": "https://github.com/x/y", "web": "https://x.example"}, "earning_miners": 40, "top_share": 0.1,
         "owner_burn_share": 0.0, "emission_day": 50.0, "miner_pool_day": 20.0, "registration_allowed": True, "uid_available": True,
         "top_miner": 1.0, "median_miner": 0.2, "reg_cost": 0.5, "price_change_7d": 0.02, "tier": "gpu", "tao_flow_day": 3.0, "age_days": 200}
    r.update(kw)
    return r


def codes(r, usd=400):
    return {f["code"]: f["level"] for f in risk.flags(r, usd)}


class Flags(unittest.TestCase):
    def test_healthy_subnet_has_no_flags(self):
        self.assertEqual(risk.flags(subnet(), 400), [])
        self.assertIsNone(risk.level([]))

    def test_anonymous_with_emission_is_a_scam_signal(self):
        r = subnet(description="", links={})
        self.assertEqual(codes(r)["anonymous"], "scam")
        self.assertEqual(risk.level(risk.flags(r, 400)), "scam")

    def test_anonymous_without_emission_is_avoid(self):
        self.assertEqual(codes(subnet(description="", links={}, emission_day=0))["anonymous"], "avoid")

    def test_owner_capture(self):
        self.assertEqual(codes(subnet(owner_burn_share=0.95, earning_miners=2))["owner_capture"], "scam")

    def test_registration_closed_beats_no_uid(self):
        c = codes(subnet(registration_allowed=False, uid_available=False))
        self.assertIn("reg_closed", c)
        self.assertNotIn("no_uid", c)

    def test_slow_payback_and_dust(self):
        c = codes(subnet(reg_cost=20, median_miner=0.2, top_miner=0.001))
        self.assertEqual(c["slow_payback"], "avoid")
        self.assertEqual(c["dust"], "avoid")

    def test_dust_needs_a_price(self):
        self.assertNotIn("dust", codes(subnet(top_miner=0.001), usd=0))

    def test_winner_take_all_from_the_text(self):
        self.assertEqual(codes(subnet(conditions="Winner-takes-all: only the top miner is paid"))["winner_take_all"], "caution")

    def test_every_flag_says_what_it_rests_on(self):
        fl = {f["code"]: f["basis"] for f in risk.flags(subnet(links={}, description="", task="", emission_day=5.0, age_days=10,
                                                                    price_change_7d=-0.5, registration_allowed=False), 400)}
        self.assertEqual(fl["anonymous"], "missing")
        self.assertEqual(fl["reg_closed"], "chain")
        self.assertEqual(fl["crash"], "history")
        self.assertEqual(fl["very_new"], "history")
        self.assertTrue(set(fl.values()) <= set(risk.BASIS))
        wta = {f["code"]: f["basis"] for f in risk.flags(subnet(conditions="Winner-takes-all"), 400)}
        self.assertEqual(wta["winner_take_all"], "text")
        self.assertEqual({f["code"]: f["basis"] for f in risk.flags(subnet(top_share=0.7, earners=10), 400)}.get("winner_take_all"), "chain")

    def test_few_earners_is_not_repeated_after_a_capture_flag(self):
        c = codes(subnet(owner_burn_share=0.95, earning_miners=2))
        self.assertNotIn("few_earners", c)

    def test_level_picks_the_most_severe(self):
        fl = [{"level": "caution"}, {"level": "avoid"}, {"level": "caution"}]
        self.assertEqual(risk.level(fl), "avoid")

    def test_every_flag_explains_itself(self):
        for f in risk.flags(subnet(description="", links={}, reg_cost=20, age_days=3, price_change_7d=-0.5), 400):
            self.assertTrue(f["text"].strip(), f)


if __name__ == "__main__":
    unittest.main()
