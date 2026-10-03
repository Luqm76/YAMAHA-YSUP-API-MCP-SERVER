"""Generate a local MCP configuration using this installed Python interpreter."""
import argparse
import json
from pathlib import Path
import sys

def main():
    root=Path(__file__).resolve().parent.parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=root/'mcp_config.local.json')
    parser.add_argument('--ysup-root',type=Path,help='本机已安装 YSUP 的目录，用于线体优化')
    args=parser.parse_args()
    env={'YAMAHA_BUILDER_DATA':str(root/'data'),
         'YAMAHA_ASSOCIATIONS_DB':str(root/'data/confirmed_associations.sqlite3'),
         'YAMAHA_OPTIMIZER_WORK':str(root/'data/optimization')}
    if args.ysup_root:
        ysup=args.ysup_root.expanduser().resolve()
        if not (ysup/'System/YwOptimizer.exe').is_file():
            parser.error('YSUP 目录缺少 System/YwOptimizer.exe')
        env['YAMAHA_YSUP_ROOT']=str(ysup)
    configuration={'mcpServers':{'yamaha-program-builder':{'command':sys.executable,
                   'args':[str(root/'run_mcp.py')],'env':env}}}
    path=args.output.expanduser().resolve()
    path.write_text(json.dumps(configuration,indent=2,ensure_ascii=False),encoding='utf-8')
    print(path)


if __name__=='__main__':main()
