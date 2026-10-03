"""Absolute script entry point for MCP clients whose working directory differs."""
import argparse
from builder.mcp_server import create_mcp

parser=argparse.ArgumentParser()
parser.add_argument('--transport',choices=['stdio','streamable-http'],default='stdio')
parser.add_argument('--port',type=int,default=8766)
args=parser.parse_args()
create_mcp(port=args.port).run(transport=args.transport)
