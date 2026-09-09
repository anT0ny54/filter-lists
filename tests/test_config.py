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
    def test_required_sources_exist(self):
        cfg = load_config()
        self.assertGreaterEqual(sum(s.required for s in cfg.sources), 2)

if __name__ == "__main__": unittest.main(verbosity=2)
