"""jwmcp - MCP server for driving Jw_cad workflows with an AI agent.

Layers:
  model      in-memory drawing model (real-mm coordinates, Jw_cad attributes lg/ly/lc/lt)
  jwc_temp   parse / serialize the 外部変形 exchange file (JWC_TEMP.TXT)
  jww_read   read .jww files through ezjww and normalise them to the model
  render     PNG preview with matplotlib
  dxf_out    DXF export with ezdxf
  bridge     file-queue bridge between Jw_cad (Windows, 外部変形 .bat) and this server
  server     MCP tool surface
"""

__version__ = "0.1.0"
