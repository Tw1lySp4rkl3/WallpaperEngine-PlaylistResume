'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {run,hash,loadManifests,loadLegacy,transform,resumeState,playlistState,playlistKey,BACKUP_NAME}=require('./reference-patcher.cjs');
const originals=process.env.WE_ORIGINALS||path.resolve(__dirname,'../upload');
const manifests=loadManifests(),legacy=loadLegacy(),quiet={log:()=>{},diagnostics:false};
function fixture(t,r02=false) {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'we-r04-test-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  for(const m of manifests.filter(m=>m.kind!=='new')) {
    const dest=path.join(root,m.filename);fs.mkdirSync(path.dirname(dest),{recursive:true});
    let data=fs.readFileSync(path.join(originals,path.basename(m.filename)));
    if(r02)data=transform(data,legacy.find(x=>x.filename===m.filename),'apply');
    fs.writeFileSync(dest,data);
  }
  fs.mkdirSync(path.join(root,'bin'));
  for(const [name,data] of [['config.json','preserve-config'],['bin/playliststate.bin','preserve-native-state'],['bin/pi-playlist-resume-r03.bin',fs.readFileSync(path.join(__dirname,'cache-format-fixture.bin'))]])fs.writeFileSync(path.join(root,name),data);
  return root;
}
function check(root,state) {
  for(const m of manifests) {
    const file=path.join(root,m.filename);
    if(state==='original'&&m.kind==='new'){assert.equal(fs.existsSync(file),false);continue;}
    assert.equal(hash(fs.readFileSync(file)),m[state==='original'?'original_sha256':'patched_sha256'],m.filename);
  }
}
function checkR02(root) {
  for(const m of legacy)assert.equal(hash(fs.readFileSync(path.join(root,m.filename))),m.patched_sha256);
  for(const m of manifests.filter(x=>x.kind==='new'))assert.equal(fs.existsSync(path.join(root,m.filename)),false);
}
test('status accepts original EXEs/UI and absent optional DLLs without creating files',t=>{
  const root=fixture(t);assert.deepEqual(run('status',root,quiet).map(x=>x.state),['original','original','original','absent','absent']);
  assert.equal(fs.existsSync(path.join(root,BACKUP_NAME)),false);
});
test('all five files install, repeated apply is idempotent, inverse restores exact originals',t=>{
  const root=fixture(t);run('apply',root,quiet);check(root,'patched');
  assert.deepEqual(run('apply',root,quiet),[]);
  for(const m of manifests.filter(m=>m.kind!=='new'))assert.equal(hash(fs.readFileSync(path.join(root,BACKUP_NAME,m.filename))),m.original_sha256);
  run('restore',root,quiet);check(root,'original');assert.deepEqual(run('restore',root,quiet),[]);
  assert.equal(fs.readFileSync(path.join(root,'config.json'),'utf8'),'preserve-config');
  assert.equal(fs.readFileSync(path.join(root,'bin/playliststate.bin'),'utf8'),'preserve-native-state');
  assert.equal(fs.existsSync(path.join(root,'bin/pi-playlist-resume-r03.bin')),false);
  assert.equal(resumeState(fs.readFileSync(path.join(root,'bin/playlist-resume.bin')))[0].position,4);
});
test('direct R02 upgrade first reconstructs originals and keeps original backups',t=>{
  const root=fixture(t,true);run('apply',root,quiet);check(root,'patched');
  for(const m of legacy)assert.equal(hash(fs.readFileSync(path.join(root,BACKUP_NAME,m.filename))),m.original_sha256);
  run('restore',root,quiet);check(root,'original');
});
test('R04 restore can also recover a known R02 installation',t=>{
  const root=fixture(t,true);run('restore',root,quiet);check(root,'original');
});
test('restoration does not require backup files',t=>{
  const root=fixture(t);run('apply',root,quiet);fs.rmSync(path.join(root,BACKUP_NAME),{recursive:true});
  run('restore',root,quiet);check(root,'original');
});
test('one unknown UI or executable prevents DLL creation and all mutations',t=>{
  for(const filename of ['wallpaper64.exe','ui/dist/scripts/scripts.js']) {
    const root=fixture(t),file=path.join(root,filename);fs.appendFileSync(file,'changed');
    const before=hash(fs.readFileSync(file));assert.throws(()=>run('apply',root,quiet),/Unbekannte/);
    assert.equal(hash(fs.readFileSync(file)),before);
    assert.equal(fs.existsSync(path.join(root,'PlaylistResume32.dll')),false);
    assert.equal(fs.existsSync(path.join(root,BACKUP_NAME)),false);
  }
});
test('an unknown same-named DLL is never overwritten',t=>{
  const root=fixture(t),file=path.join(root,'PlaylistResume32.dll');fs.writeFileSync(file,'foreign DLL');
  assert.throws(()=>run('apply',root,quiet),/Unbekannte/);
  assert.equal(fs.readFileSync(file,'utf8'),'foreign DLL');
  assert.equal(hash(fs.readFileSync(path.join(root,'wallpaper32.exe'))),manifests[0].original_sha256);
});
test('bad DLL payload is refused before backups or executable writes',t=>{
  const root=fixture(t),bad=structuredClone(manifests);bad[3].contents_hex='00'+bad[3].contents_hex.slice(2);
  assert.throws(()=>run('apply',root,{...quiet,manifests:bad}),/DLL-Inhalt/);
  check(root,'original');assert.equal(fs.existsSync(path.join(root,BACKUP_NAME)),false);
});
test('invalid native offsets, overlap and nonunique UI replacements are refused',t=>{
  const root=fixture(t),data=fs.readFileSync(path.join(root,manifests[0].filename));
  let bad=structuredClone(manifests[0]);bad.changes[0].offset=-1;
  assert.throws(()=>transform(data,bad,'apply'),/Patchbereich/);
  bad=structuredClone(manifests[0]);bad.changes.push(bad.changes[0]);
  assert.throws(()=>transform(data,bad,'apply'),/Patchbereich/);
  const changed=structuredClone(manifests);changed[2].replacements[0].before='missing text';
  assert.throws(()=>run('apply',root,{...quiet,manifests:changed}),/UI-Patchbereich/);check(root,'original');
});
for(const failAt of [2,3,4,5])test('replacement failure '+failAt+' restores originals and removes newly created DLLs',t=>{
  const root=fixture(t),real=fs.renameSync;let count=0;
  const stub=t.mock.method(fs,'renameSync',function(...args){if(++count===failAt)throw new Error('simulated locked file');return real.apply(this,args);});
  assert.throws(()=>run('apply',root,quiet),/simulated locked file/);stub.mock.restore();check(root,'original');
});
test('a failed R02 upgrade returns exactly to R02, with no new helper DLLs',t=>{
  const root=fixture(t,true),real=fs.renameSync;let count=0;
  const stub=t.mock.method(fs,'renameSync',function(...args){if(++count===4)throw new Error('simulated R02 upgrade failure');return real.apply(this,args);});
  assert.throws(()=>run('apply',root,quiet),/simulated R02 upgrade failure/);stub.mock.restore();checkR02(root);
});
test('failure deleting the second DLL during restore rebuilds the complete R04 installation',t=>{
  const root=fixture(t);run('apply',root,quiet);const real=fs.unlinkSync;let failed=false;
  const stub=t.mock.method(fs,'unlinkSync',function(file,...args){if(!failed&&file===path.join(root,'PlaylistResume64.dll')){failed=true;throw new Error('simulated locked DLL');}return real.call(this,file,...args);});
  assert.throws(()=>run('restore',root,quiet),/simulated locked DLL/);stub.mock.restore();check(root,'patched');
});
test('an altered backup is preserved and blocks mutation',t=>{
  const root=fixture(t),backup=path.join(root,BACKUP_NAME);fs.mkdirSync(backup);fs.writeFileSync(path.join(backup,'wallpaper32.exe'),'altered');
  assert.throws(()=>run('apply',root,quiet),/Sicherung ist veraendert/);check(root,'original');
  assert.equal(fs.readFileSync(path.join(backup,'wallpaper32.exe'),'utf8'),'altered');
});
test('missing known helper DLLs can be repaired without rewriting patched executables',t=>{
  const root=fixture(t);run('apply',root,quiet);fs.unlinkSync(path.join(root,'PlaylistResume32.dll'));
  const changed=run('apply',root,quiet);assert.deepEqual(changed.map(x=>x.filename),['PlaylistResume32.dll']);check(root,'patched');
});
test('latest failure snapshot contains three zero counters without a lost checkbox option',
{skip:!fs.existsSync(path.join(originals,'config(1).json'))||!fs.existsSync(path.join(originals,'playliststate(1).bin'))},()=>{
  const config=JSON.parse(fs.readFileSync(path.join(originals,'config(1).json'),'utf8'));
  const active=Object.values(config).find(user=>user?.general?.wallpaperconfig?.selectedwallpapers).general.wallpaperconfig.selectedwallpapers;
  const records=playlistState(fs.readFileSync(path.join(originals,'playliststate(1).bin')));
  const enabled=Object.entries(active).filter(([_,e])=>e.playlist?.settings.rememberposition);
  assert.equal(enabled.length,3);
  for(const [monitor] of enabled)assert.equal(records.find(x=>x.monitor===monitor).checkpoint,0);
});
test('the independent cache format rejects truncation, invalid counts and bad checksums',()=>{
  const data=fs.readFileSync(path.join(__dirname,'cache-format-fixture.bin'));
  const records=resumeState(data);assert.equal(records.length,1);assert.equal(records[0].position,4);
  const playlist={items:Array.from({length:10},(_,i)=>'WP_'+String(i+1).padStart(5,'0'))};
  assert.equal(playlistKey('DISPLAY_TEST_1',playlist),records[0].key,'C DLL core and Node diagnostics use the same identity');
  assert.throws(()=>resumeState(data.subarray(0,20)),/beschaedigt/);
  const bad=Buffer.from(data);bad[bad.length-1]^=1;assert.throws(()=>resumeState(bad),/beschaedigt/);
  assert.notEqual(playlistKey('DISPLAY_TEST_2',playlist),records[0].key);
  assert.notEqual(playlistKey('DISPLAY_TEST_1',{items:[...playlist.items].reverse()}),records[0].key);
});
