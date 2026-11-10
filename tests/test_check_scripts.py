"""D2 确定性检查脚本核心逻辑测试（2026-11-11）。

重点锁「对历史失实样例能报错」：v3.9.1 CHANGELOG「零代码」宣称 × 6 个
代码提交的实况（2026-11-10 审计硬违规 #2）必须被 verify_section 报错。
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

from check_changelog_claims import is_code_commit, section_claims, verify_section  # noqa: E402


class TestChangelogClaimsCore:
    def test_v391_historical_case_errors(self):
        """历史失实样例：零代码宣称 × 6 代码提交 → 必须报错。"""
        claims = {"zero_code": True, "claimed_code_commits": None}
        errors = verify_section(claims, code_commits=6)
        assert errors, "v3.9.1 形态（零代码宣称+代码提交）必须报错"
        assert "6" in errors[0]

    def test_zero_code_with_no_code_commits_ok(self):
        claims = {"zero_code": True, "claimed_code_commits": None}
        assert verify_section(claims, code_commits=0) == []

    def test_claimed_count_mismatch_errors(self):
        claims = {"zero_code": False, "claimed_code_commits": 3}
        errors = verify_section(claims, code_commits=6)
        assert errors and "3" in errors[0] and "6" in errors[0]

    def test_claimed_count_match_ok(self):
        claims = {"zero_code": False, "claimed_code_commits": 6}
        assert verify_section(claims, code_commits=6) == []

    def test_section_claims_extraction(self):
        claims = section_claims("本版为零代码维护版，无任何代码改动")
        assert claims["zero_code"] is True
        assert claims["claimed_code_commits"] is None

    def test_section_claims_corrected_context(self):
        """勘误语境里的「零代码」字样不算有效宣称（v3.9.1 勘误后形态）。"""
        text = "接手清偿发版（原说明「零代码」已于 2026-11-10 勘误）……实含 6 个代码提交清单"
        claims = section_claims(text)
        assert claims["zero_code"] is False
        assert claims["claimed_code_commits"] == 6


class TestIsCodeCommit:
    def test_python_file_is_code(self):
        assert is_code_commit(["tradex/src/tradex/service/price_service.py"])

    def test_docs_only_not_code(self):
        assert not is_code_commit(["README.md", "CHANGELOG.md", "docs/MCP_TOOLS.md"])

    def test_requirements_is_code(self):
        assert is_code_commit(["tradex/requirements.txt"])
