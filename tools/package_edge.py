"""Build private delivery archives locally; never package business databases."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
SKIP={'.git','.venv','.uv-cache','.pytest_cache','__pycache__','node_modules','.next',
      '.next-collection-demo','runtime','private','test-results','.tools','.python','data','examples'}
FORBIDDEN={'.db','.sqlite','.dump','.pyc','.zip','.pt','.pth','.npz'}


def sources():
    for folder in ('backend','frontend','deploy/edge'):
        for path in (ROOT/folder).rglob('*'):
            relative=path.relative_to(ROOT)
            if not path.is_file() or path.is_symlink() or any(p in SKIP for p in relative.parts):continue
            if path.name=='.env' or path.name.startswith('.env.') or path.suffix.lower() in FORBIDDEN:continue
            yield path,relative.as_posix()


def main():
    parser=argparse.ArgumentParser(description='Packages contain private connection credentials; keep them out of Git.')
    parser.add_argument('--private-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'runtime/bundles')
    parser.add_argument('--uv',default='uv')
    args=parser.parse_args()
    private=args.private_dir.resolve();output=args.output_dir.resolve()
    output.mkdir(parents=True,exist_ok=True)
    subprocess.run([args.uv,'export','--project',str(ROOT/'backend'),'--format','requirements-txt',
        '--no-dev','--no-hashes','--python',sys.executable,'--output-file',str(output/'requirements-server.txt')],
        check=True,stdout=subprocess.DEVNULL)
    pi_files={'edge.env':'edge.env','connection.env':'connection.env','edge_ed25519':'edge_ed25519','known_hosts':'known_hosts'}
    viewer_files={'reports_ed25519':'reports_ed25519','known_hosts':'known_hosts','reports-connection.json':'connection.json'}
    for name in set(pi_files)|set(viewer_files):
        if not (private/name).is_file():raise SystemExit('Missing private delivery file: '+name)
    pi=output/'robot-care-raspberry-pi-private.zip'
    with ZipFile(pi,'w',ZIP_DEFLATED) as bundle:
        for path,name in sources():bundle.write(path,name)
        for source,target in pi_files.items():bundle.write(private/source,'private/'+target)
        bundle.write(output/'requirements-server.txt','requirements-server.txt')
        bundle.write(ROOT/'docs/PROJECT_HANDOFF_2026-11-22.md','README-交接与使用手册.md')
        bundle.write(ROOT/'docs/operations/edge-central.md','README-部署说明.md')
        bundle.write(ROOT/'.gitignore','.gitignore')
    viewer=output/'robot-care-administrator-windows-private.zip'
    with ZipFile(viewer,'w',ZIP_DEFLATED) as bundle:
        for name in ('Open-Reports.cmd','Open-Reports.ps1'):bundle.write(ROOT/'deploy/reports-windows'/name,name)
        for source,target in viewer_files.items():bundle.write(private/source,'private/'+target)
        bundle.writestr('使用说明.txt','解压后运行 Open-Reports.cmd，使用授权的服务器管理员账号登录。需要 Windows OpenSSH Client 和 Chrome。此私有包仅含报告转发凭据，不含数据库密码或豆包密钥。')
    result={p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (pi,viewer)}
    (output/'package-manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'output_directory':str(output),'private_packages':list(result)}))


if __name__=='__main__':main()
