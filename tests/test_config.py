import tempfile
import unittest
from pathlib import Path
import sys
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as config_module
from config import canonical_url, load_config, valid_url

from _helpers import setup_config_root

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


    def test_duplicate_urls_are_checked_after_canonicalization(self):
        setup_config_root(self, config_module, sources_yaml="""sources:
  - name: first
    url: https://EXAMPLE.com/list#one
    enabled: true
  - name: second
    url: https://example.com/list#two
    enabled: true
""", policies_yaml="""limits: {}
source_health: {}
history: {}
anomaly_detection:
  enabled: false
""")
        with self.assertRaisesRegex(ValueError, "duplicate canonical URL"):
            config_module.load_config()

    def test_anomaly_detection_policy_is_loaded(self):
        cfg = load_config()
        self.assertTrue(cfg.anomaly_detection["enabled"])
        self.assertEqual(cfg.anomaly_detection["min_lines"], 100)
        self.assertFalse(cfg.anomaly_detection["fail_on_warning"])

    def test_source_booleans_are_real_yaml_booleans(self):
        cfg = load_config()
        self.assertTrue(all(isinstance(s.enabled, bool) for s in cfg.sources))
        self.assertTrue(all(isinstance(s.required, bool) for s in cfg.sources))
        self.assertTrue(all(isinstance(s.trusted_abp_features, bool) for s in cfg.sources))

    def test_required_source_cannot_be_disabled(self):
        setup_config_root(self, config_module, sources_yaml="""sources:
  - name: required-but-disabled
    url: https://example.com/list.txt
    enabled: false
    required: true
""", policies_yaml="""limits: {}
source_health: {}
history: {}
anomaly_detection:
  enabled: false
""")
        with self.assertRaisesRegex(ValueError, "cannot be required and disabled"):
            config_module.load_config()

    def test_policy_limits_require_real_integers(self):
        setup_config_root(self, config_module, sources_yaml="""sources:
  - name: source
    url: https://example.com/list.txt
    enabled: true
""", policies_yaml="""limits:
  max_download_bytes: 1.5
source_health: {}
history: {}
anomaly_detection:
  enabled: false
""")
        with self.assertRaisesRegex(ValueError, "max_download_bytes must be an integer"):
            config_module.load_config()

    def test_policy_ratios_require_real_numbers(self):
        setup_config_root(self, config_module, sources_yaml="""sources:
  - name: source
    url: https://example.com/list.txt
    enabled: true
""", policies_yaml="""limits: {}
source_health:
  minimum_success_ratio: "0.80"
history: {}
anomaly_detection:
  enabled: false
""")
        with self.assertRaisesRegex(ValueError, "minimum_success_ratio must be a number"):
            config_module.load_config()

    def test_policy_booleans_require_real_yaml_booleans(self):
        setup_config_root(self, config_module, sources_yaml="""sources:
  - name: source
    url: https://example.com/list.txt
    enabled: true
""", policies_yaml="""limits: {}
source_health:
  fail_if_zero_sources: "false"
history: {}
anomaly_detection:
  enabled: false
""")
        with self.assertRaisesRegex(ValueError, "source_health.fail_if_zero_sources must be a boolean"):
            config_module.load_config()

    def test_source_urls_reject_leading_and_trailing_whitespace(self):
        for url in (" https://example.com/list.txt", "https://example.com/list.txt ", "\thttps://example.com/list.txt"):
            with self.subTest(url=repr(url)):
                setup_config_root(
                    self,
                    config_module,
                    sources_yaml=(
                        "sources:\n"
                        "  - name: source\n"
                        f"    url: {yaml.safe_dump(url, default_flow_style=True, allow_unicode=True).strip()}\n"
                    ),
                    policies_yaml="limits: {}\n",
                )
                with self.assertRaisesRegex(ValueError, "invalid source"):
                    config_module.load_config()

    def test_urls_reject_credentials_and_malformed_ports(self):
        self.assertFalse(valid_url("https://user:secret@example.com/list.txt"))
        self.assertFalse(valid_url("https://example.com:not-a-port/list.txt"))
        self.assertFalse(valid_url("https://example.com:/list.txt"))
        self.assertTrue(valid_url("https://example.com:443/list.txt"))

    def test_urls_reject_raw_control_characters(self):
        for control in ("\x00", "\x01", "\x1f", "\x7f", "\x85", "\x9f"):
            with self.subTest(control=repr(control)):
                self.assertFalse(valid_url(f"https://example.com/a{control}b"))

    def test_canonical_url_does_not_trim_invalid_whitespace(self):
        for url in (" https://example.com/list.txt", "https://example.com/list.txt ", "\thttps://example.com/list.txt"):
            with self.subTest(url=repr(url)), self.assertRaises(ValueError):
                canonical_url(url)

    def test_canonical_url_does_not_erase_an_invalid_port(self):
        with self.assertRaises(ValueError):
            canonical_url("https://example.com:99999/list.txt")

    def test_duplicate_keys_in_source_registry_are_rejected(self):
        setup_config_root(
            self,
            config_module,
            sources_yaml="""sources:
  - name: source
    url: https://example.com/list.txt
    enabled: true
    enabled: false
""",
            policies_yaml="limits: {}\n",
        )
        with self.assertRaisesRegex(ValueError, "(?s)sources.yaml: invalid YAML:.*duplicate key 'enabled'"):
            config_module.load_config()

    def test_duplicate_keys_in_policy_are_rejected(self):
        setup_config_root(
            self,
            config_module,
            sources_yaml="sources:\n  - name: source\n    url: https://example.com/list.txt\n",
            policies_yaml="""limits:
  max_download_bytes: 1024
  max_download_bytes: 524288000
""",
        )
        with self.assertRaisesRegex(ValueError, "(?s)policies.yaml: invalid YAML:.*duplicate key 'max_download_bytes'"):
            config_module.load_config()

    def test_falsy_non_mapping_yaml_roots_are_not_coerced_to_empty_mappings(self):
        setup_config_root(
            self,
            config_module,
            sources_yaml="sources:\n  - name: source\n    url: https://example.com/list.txt\n",
            policies_yaml="false\n",
        )
        with self.assertRaisesRegex(ValueError, "policies.yaml: top level must be an object"):
            config_module.load_config()

        setup_config_root(
            self,
            config_module,
            sources_yaml="false\n",
            policies_yaml="limits: {}\n",
        )
        with self.assertRaisesRegex(ValueError, "sources.yaml: top level must be an object"):
            config_module.load_config()

    def test_yaml_merge_keys_keep_standard_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.yaml"
            path.write_text(
                "defaults: &defaults\n  max_download_bytes: 1024\n"
                "limits:\n  <<: *defaults\n  max_download_bytes: 2048\n",
                encoding="utf-8",
            )
            data = config_module._load_yaml_file(path, "policies.yaml")
        self.assertEqual(data["limits"]["max_download_bytes"], 2048)


if __name__ == "__main__":
    unittest.main(verbosity=2)
