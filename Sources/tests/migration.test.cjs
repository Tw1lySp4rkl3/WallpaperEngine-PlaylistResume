'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {run,hash,loadManifests,loadR03,transform,resumeState,crc32,BACKUP_NAME}=require('./reference-patcher.cjs');
const originals=process.env.WE_ORIGINALS||path.resolve(__dirname,'../upload');
const current=loadManifests(),previous=loadR03(),quiet={log:()=>{},diagnostics:false};
const legacyCache=fs.readFileSync(path.join(__dirname,'cache-format-fixture.bin'));

function fixture(t,r03=true) {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'playlist-resume-migration-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  for(const m of previous) {
    if(!r03&&m.kind==='new')continue;
    const input=m.kind==='new'?null:fs.readFileSync(path.join(originals,path.basename(m.filename)));
    const file=path.join(root,m.filename);fs.mkdirSync(path.dirname(file),{recursive:true});
    fs.writeFileSync(file,r03?transform(input,m,'apply'):input);
  }
  fs.mkdirSync(path.join(root,'bin'));
  fs.writeFileSync(path.join(root,'bin/pi-playlist-resume-r03.bin'),legacyCache);
  fs.writeFileSync(path.join(root,'bin/pi-playlist-resume-r03.log'),'checkpoint monitor=0000000000000001 position=4 detail=10\r\n');
  return root;
}
function snapshot(root) {
  const names=[...new Set([...current,...previous].map(m=>m.filename)),'bin/pi-playlist-resume-r03.bin',
    'bin/playlist-resume.bin','bin/pi-playlist-resume-r03.log','bin/playlist-resume.log'];
  return Object.fromEntries(names.map(name=>[name,fs.existsSync(path.join(root,name))?hash(fs.readFileSync(path.join(root,name))):null]));
}
function checkCurrent(root) {
  for(const m of current)assert.equal(hash(fs.readFileSync(path.join(root,m.filename))),m.patched_sha256);
  for(const m of previous.filter(m=>m.kind==='new'))assert.equal(fs.existsSync(path.join(root,m.filename)),false);
}

test('direct R03 upgrade uses neutral names and preserves exact checkpoint records and logs',t=>{
  const root=fixture(t);run('apply',root,quiet);checkCurrent(root);
  const migrated=fs.readFileSync(path.join(root,'bin/playlist-resume.bin'));
  assert.equal(migrated.toString('ascii',0,8),'WPRS0001');assert.deepEqual(migrated.subarray(8),legacyCache.subarray(8));
  assert.equal(resumeState(migrated)[0].position,4);
  assert.equal(fs.existsSync(path.join(root,'bin/pi-playlist-resume-r03.bin')),false);
  assert.equal(fs.existsSync(path.join(root,'bin/pi-playlist-resume-r03.log')),false);
  assert.deepEqual(fs.readFileSync(path.join(root,BACKUP_NAME,'bin/pi-playlist-resume-r03.bin')),legacyCache);
  assert.equal(fs.readFileSync(path.join(root,'bin/playlist-resume.log'),'utf8'),'checkpoint monitor=0000000000000001 position=4 detail=10\r\n');
  assert.deepEqual(run('apply',root,quiet),[]);
  run('restore',root,quiet);
  for(const m of current.filter(m=>m.kind!=='new'))assert.equal(hash(fs.readFileSync(path.join(root,m.filename))),m.original_sha256);
  for(const m of [...current,...previous].filter(m=>m.kind==='new'))assert.equal(fs.existsSync(path.join(root,m.filename)),false);
  assert.deepEqual(fs.readFileSync(path.join(root,'bin/playlist-resume.bin')),migrated);
});

test('an existing valid neutral cache wins over an older R03 cache',t=>{
  const root=fixture(t),data=Buffer.from(legacyCache);data.write('WPRS0001',0,'ascii');data.writeUInt32LE(6,36);
  data.writeUInt32LE(crc32(data.subarray(16)),12);fs.writeFileSync(path.join(root,'bin/playlist-resume.bin'),data);
  run('apply',root,quiet);assert.deepEqual(fs.readFileSync(path.join(root,'bin/playlist-resume.bin')),data);
  assert.equal(resumeState(data)[0].position,7);
});

test('unknown old DLLs and corrupt legacy caches stop before any program mutation',t=>{
  for(const name of ['PiPlaylistResume64.dll','bin/pi-playlist-resume-r03.bin']) {
    const root=fixture(t);fs.appendFileSync(path.join(root,name),'unexpected');const before=snapshot(root);
    assert.throws(()=>run('apply',root,quiet),/Unbekannte alte DLL|beschaedigt/);
    assert.deepEqual(snapshot(root),before);assert.equal(fs.existsSync(path.join(root,BACKUP_NAME)),false);
  }
});

for(const failAt of [1,2,3,4,5,6,7])test('failed R03 migration rename '+failAt+' returns all code/cache/log bytes to R03',t=>{
  const root=fixture(t),before=snapshot(root),real=fs.renameSync;let count=0;
  const stub=t.mock.method(fs,'renameSync',function(...args){if(++count===failAt)throw new Error('migration write failure');return real.apply(this,args);});
  assert.throws(()=>run('apply',root,quiet),/migration write failure/);stub.mock.restore();
  assert.deepEqual(snapshot(root),before);
});

for(const filename of ['PiPlaylistResume64.dll','bin/pi-playlist-resume-r03.bin','bin/pi-playlist-resume-r03.log'])
test('failed removal of '+filename+' rolls the complete upgrade back',t=>{
  const root=fixture(t),before=snapshot(root),real=fs.unlinkSync;let failed=false;
  const stub=t.mock.method(fs,'unlinkSync',function(file,...args){
    if(!failed&&file===path.join(root,filename)){failed=true;throw new Error('migration delete failure');}
    return real.call(this,file,...args);
  });
  assert.throws(()=>run('apply',root,quiet),/migration delete failure/);stub.mock.restore();assert.deepEqual(snapshot(root),before);
});

test('R03 can be restored directly and missing old DLLs do not prevent upgrading',t=>{
  let root=fixture(t);run('restore',root,quiet);
  assert.deepEqual(fs.readFileSync(path.join(root,'bin/pi-playlist-resume-r03.bin')),legacyCache);
  for(const m of current.filter(m=>m.kind!=='new'))assert.equal(hash(fs.readFileSync(path.join(root,m.filename))),m.original_sha256);
  root=fixture(t);fs.unlinkSync(path.join(root,'PiPlaylistResume32.dll'));run('apply',root,quiet);checkCurrent(root);
});

test('fresh installation creates no empty checkpoint file and contains no personal filenames',t=>{
  const root=fixture(t,false);fs.unlinkSync(path.join(root,'bin/pi-playlist-resume-r03.bin'));
  fs.unlinkSync(path.join(root,'bin/pi-playlist-resume-r03.log'));run('apply',root,quiet);checkCurrent(root);
  assert.equal(fs.existsSync(path.join(root,'bin/playlist-resume.bin')),false);
});
