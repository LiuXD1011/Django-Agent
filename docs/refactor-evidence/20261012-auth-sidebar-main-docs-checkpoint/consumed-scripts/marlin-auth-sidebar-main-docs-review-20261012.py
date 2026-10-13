from pathlib import Path
ROOT=Path('/home/liuxuedeng/Django-Agent')
for name in ['STATUS.md','TEST-MATRIX.md']:
    p=ROOT/'docs/desktop-refactor'/name;s=p.read_text()
    s=s.replace('1440×900与1024×768/DPI96评测表格可读，但1024侧栏两导航按钮accessible name为空，Root确认待修，不计全布局或J-04通过。','旧99ba安装版1440×900与1024×768/DPI96评测表格可读，但其1024侧栏导航名称为空的失败保持；源码属性现已修复并核DOM，新安装1024 UIA/导航仍待复验，不计全布局或J-04通过。',1)
    if name=='STATUS.md':s=s.replace('最新[集成来源](../refactor-evidence/20261012-web-search-result-integrated-source-freeze.json)仍为SHA256','前一5cab[集成来源](../refactor-evidence/20261012-web-search-result-integrated-source-freeze.json)为SHA256',1)
    else:
        old=next(line for line in s.splitlines() if line.startswith('最新检查为核心完整'))
        new='核心仍保留109文件695项=693PASS/0FAIL/2条件SKIP，另plain Node compiled2/2，438 core产物在新来源保持；当前侧栏前端361/361及Vite build退出0，旧P2/360历史保留，源码/安装条件见下文。MCP实际留空Key编辑/启停、唯一GLM工具948/新回执和自有清理不填满I/E/J。[核心全套](../refactor-evidence/20261012-web-search-alias-final-core-checks/full-execution.json)、[compiled](../refactor-evidence/20261012-web-search-alias-final-core-checks/compiled-execution.json)、[当前前端](../refactor-evidence/20261012-sidebar-accessible-names/unit-execution.json)、[当前build](../refactor-evidence/20261012-sidebar-accessible-names/build-execution.json)、[真实MCP](MCP-REAL-AGENT-BROWSER.md)。'
        s=s.replace(old,new,1)
    p.write_text(s)
