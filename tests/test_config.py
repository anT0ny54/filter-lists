import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]

class ConfigTests(unittest.TestCase):
    def test_sources_yaml_matches_sources_txt(self):
        yaml_urls = [x["url"] for x in yaml.safe_load((ROOT / "sources.yaml").read_text())["sources"]]
        txt_urls = [x.strip() for x in (ROOT / "sources.txt").read_text().splitlines() if x.strip() and not x.strip().startswith("#")]
        self.assertEqual(yaml_urls, txt_urls)
    def test_policy_profile_is_strict_abp(self):
        policy = yaml.safe_load((ROOT / "policies.yaml").read_text())
        self.assertEqual(policy["profile"], "strict-abp")
        self.assertTrue(policy["rules"]["reject_ubo_procedural"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
