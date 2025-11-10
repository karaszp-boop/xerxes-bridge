#!/usr/bin/env python3
import json, sys, os, argparse, urllib.request, urllib.error
PATH="/opt/xerxes-bridge/token_map.json"; PROJECT="project_hetzner"
TB_HOST=os.environ.get("TB_HOST","https://eu.thingsboard.cloud")
def load():
    if not os.path.exists(PATH): return {PROJECT:{}}
    with open(PATH) as f: data=json.load(f)
    if PROJECT not in data or not isinstance(data[PROJECT],dict):
        if isinstance(data,dict) and all(isinstance(k,str) for k in data.keys()):
            data={PROJECT:data}
        else: data={PROJECT:{}}
    return data
def save(d):
    tmp=PATH+".tmp"
    with open(tmp,"w") as f: json.dump(d,f,ensure_ascii=False,indent=2)
    os.replace(tmp,PATH); os.chmod(PATH,0o644)
def cmd_list(_):
    for u,t in load()[PROJECT].items(): print(f"{u},{t}")
def cmd_add(a):
    d=load(); m=d.setdefault(PROJECT,{})
    for p in a.mapping:
        sep="," if "," in p else (":" if ":" in p else None)
        if not sep: print(f"Bad mapping: {p} (use uuid,token)",file=sys.stderr); sys.exit(2)
        u,t=[s.strip() for s in p.split(sep,1)]; m[u]=t; print(f"[ADD] {u} -> {t}")
    save(d)
def cmd_validate(a):
    ok,bad=[],[]; d=load()[PROJECT]
    targets=[(u,d[u]) for u in (a.uuids or d.keys())]
    for u,t in targets:
        url=f"{TB_HOST}/api/v1/{t}/attributes?clientKeys=__ping__"
        try:
            with urllib.request.urlopen(url,timeout=6) as r:
                (ok if r.status==200 else bad).append(u if r.status==200 else (u,f"HTTP {r.status}"))
        except urllib.error.HTTPError as e: bad.append((u,f"HTTP {e.code}"))
        except Exception as e: bad.append((u,f"ERR {e}"))
    print("[VALID] OK:",",".join(ok) or "-")
    if bad: print("[VALID] FAIL:"); [print("  ",u,r) for u,r in bad]
if __name__=="__main__":
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd")
    sub.add_parser("list"); a=sub.add_parser("add"); a.add_argument("mapping",nargs="+")
    v=sub.add_parser("validate"); v.add_argument("--uuids",nargs="*"); args=ap.parse_args()
    {"list":cmd_list,"add":cmd_add,"validate":cmd_validate}.get(args.cmd,lambda _ : ap.print_help())(args)
