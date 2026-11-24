from pathlib import Path
import os,subprocess,json,time,sys,hashlib
root=Path(__file__).resolve().parents[2];front=root/"frontend";work=Path(__file__).resolve().parent
node=Path("C:/Users/nipun/AppData/Local/Programs/node-v24.21.0-win-x64/node.exe")
keys={"SYSTEMROOT","WINDIR","COMSPEC","TEMP","TMP","LOCALAPPDATA","APPDATA","USERPROFILE","PROGRAMFILES","PROGRAMFILES(X86)","NUMBER_OF_PROCESSORS","PROCESSOR_ARCHITECTURE","PATHEXT","PATH","SYSTEMDRIVE","PROGRAMDATA","HOMEDRIVE","HOMEPATH"}
env={k:v for k,v in os.environ.items() if k.upper() in keys};env.update(PATH=str(node.parent)+os.pathsep+env.get("PATH",""),API_BASE_URL="http://127.0.0.1:3199",NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:3199",NEXT_TELEMETRY_DISABLED="1",NO_COLOR="1")
name=sys.argv[1];files=sys.argv[2:] or ["features/branding/components/group-image-dialog.test.tsx"]
argv=[str(node),"node_modules/vitest/vitest.mjs","run",*files,"--config",str(root/".tmp/banner-crop-target/vitest.config.mts"),"--maxWorkers=1","--pool=threads"]
source_paths=["features/branding/components/group-banner.tsx","features/branding/components/group-banner-action.tsx","features/branding/components/group-image-dialog.tsx","features/branding/components/group-banner-frame.ts","features/branding/components/use-group-image-aspect.ts","features/branding/components/group-image-dialog.test.tsx","features/branding/components/group-image-save-authority.test.tsx","features/branding/image-crop.ts","features/branding/image-crop.test.ts","features/branding/api/branding-images.api.ts","features/branding/api/branding-images.api.test.ts"]
def source_fence():return {"frontend/"+p:hashlib.sha256((front/p).read_bytes()).hexdigest() for p in source_paths}
before=source_fence()
started=time.monotonic()
with (work/(name+".log")).open("wb") as f:r=subprocess.run(argv,cwd=front,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=120)
(work/(name+"-command.json")).write_text(json.dumps({"argv":argv,"cwd":"frontend","exit_code":r.returncode,"seconds":time.monotonic()-started,"envDir":False,"source_fence":before,"source_unchanged":before==source_fence()},indent=2)+"\n",encoding="utf-8");print(r.returncode)
