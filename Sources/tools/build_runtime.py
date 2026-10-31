"""Rebuild the unchanged Windows-confirmed runtime with v1.0 manifest metadata."""
import json
import build_r04
from patch_catalog import load_catalog
def main():
    current=load_catalog()['current']
    build_r04.main()
    for file in build_r04.OUT.glob('*.patch.json'):
        m=json.loads(file.read_text());m['revision']=current['version']
        file.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
    names=['wallpaper32.patch.json','wallpaper64.patch.json','scripts.patch.json','PlaylistResume32.patch.json','PlaylistResume64.patch.json']
    current['files']=[json.loads((build_r04.OUT/name).read_text()) for name in names]
    (build_r04.OUT/'patches.json').write_text(json.dumps(current,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
