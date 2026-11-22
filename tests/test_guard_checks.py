"""D2 确定性检查挂载测试（2026-11-11 裁决③：老板授权 AI 定挂载方式）。

决定：检查核心进**全量回归门**——每次施工验证门自动核验，零环境依赖
（不依赖 pre-commit 安装、无 GitHub Actions）；CLI 手动用法保留（发版前跑）。

- check_dep_sync.main()             → 0 一致
- check_readme_counts.main()        → 0 计数一致（MCP/REST/注册/类型）
- check_changelog_claims.main()     → 0 措辞与 git log 一致
- check_undeclared_imports.main()   → 0 import×声明比对全过（2026-11-14 Issue #2 护栏）
- check_pyflakes.main()             → 0 全仓零 F821 未定义名（2026-11-22 QI-RETRO-03 护栏）
- check_exit_shapes.main()          → 0 MCP 出口形态 × EXEMPTIONS 表一一致（2026-11-22 QI-RETRO-02 护栏）
- REST 端点数断言另见 tests/test_rest_count.py（独立更快）
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))


class TestGuardChecksMain:
    def test_dep_sync(self):
        from check_dep_sync import main

        assert main() == 0, "依赖双处漂移（硬违规#1 形态）——看脚本输出定位缺失包"

    def test_readme_counts(self):
        from check_readme_counts import main

        assert main() == 0, "README 计数与实跑不一致——改计数四处一体（README/断言/CHANGELOG/MCP_TOOLS）"

    def test_changelog_claims(self):
        from check_changelog_claims import main

        assert main() == 0, "CHANGELOG 措辞与 git log 史实不符（v3.9.1 失实教训）"

    def test_undeclared_imports(self):
        from check_undeclared_imports import main

        assert main() == 0, "存在 import 未声明的第三方包（传递依赖侥幸形态）——补声明双处或白名单注明降级依据"

    def test_pyflakes_undefined_names(self):
        from check_pyflakes import main

        assert main() == 0, "存在 F821 未定义名（NameError 级编程错误，QI-BUG-01 教训）——补 import 或修正引用，不带病挂门"

    def test_exit_shapes(self):
        from check_exit_shapes import main

        assert main([]) == 0, "MCP 出口形态与 EXEMPTIONS.md 表一漂移——手写出口先登记豁免（经老板确认），已收拢工具同步清理豁免行"
