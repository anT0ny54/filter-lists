import unittest
from pathlib import Path
import sys
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from config import load_config

ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_sources_yaml_is_single_source_of_truth(self):
        cfg = load_config()
        yaml_urls = [x.url for x in cfg.sources]
        txt = [x.strip() for x in (ROOT / "sources.txt").read_text().splitlines() if x.strip() and not x.startswith("#")]
        self.assertEqual(yaml_urls, txt)

    def test_policy_profile_is_strict_abp(self):
        policy = yaml.safe_load((ROOT / "policies.yaml").read_text())
        self.assertEqual(policy["profile"], "strict-abp")
        self.assertEqual(policy["source_health"]["minimum_success_ratio"], 0.80)

    def test_limits_are_loaded_from_policy(self):
        cfg = load_config()
        policy = yaml.safe_load((ROOT / "policies.yaml").read_text())
        self.assertEqual(cfg.max_rule_length, policy["limits"]["max_rule_length"])
        self.assertEqual(cfg.max_download_bytes, policy["limits"]["max_download_bytes"])
        self.assertEqual(cfg.max_total_download_bytes, policy["limits"]["max_total_download_bytes"])
        self.assertEqual(cfg.max_total_sources, policy["limits"]["max_total_sources"])

    def test_required_sources_exist(self):
        cfg = load_config()
        self.assertGreaterEqual(sum(s.required for s in cfg.sources), 2)

    def test_anomaly_detection_policy_is_loaded(self):
        cfg = load_config()
        self.assertTrue(cfg.anomaly_detection["enabled"])
        self.assertEqual(cfg.anomaly_detection["min_lines"], 100)
        self.assertFalse(cfg.anomaly_detection["fail_on_warning"])

    def test_source_booleans_are_real_yaml_booleans(self):
        cfg = load_config()
        self.assertTrue(all(isinstance(s.enabled, bool) for s in cfg.sources))
        self.assertTrue(all(isinstance(s.required, bool) for s in cfg.sources))


if __name__ == "__main__":
    unittest.main(verbosity=2)
