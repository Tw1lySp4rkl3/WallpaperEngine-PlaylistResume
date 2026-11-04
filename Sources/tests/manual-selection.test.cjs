'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {loadManifests,transform}=require('./reference-patcher.cjs');
const originals=process.env.WE_ORIGINALS||path.resolve(__dirname,'../upload');
const manifest=loadManifests().find(m=>m.kind==='text');
const script=transform(fs.readFileSync(path.join(originals,'scripts.js')),manifest,'apply').toString('utf8');

function browser(settings={},options={}) {
  const wallpapers=Array.from({length:10},(_,i)=>({file:'WP_'+String(i+1).padStart(5,'0'),title:'Wallpaper '+(i+1),status:'installed',type:'Scene'}));
  const playlist={name:'Test playlist',settings:{mode:'timer',order:'sorted',beginfirst:true,rememberposition:true,...settings},items:wallpapers.map(w=>({wallpaper:w}))};
  const monitor={location:'DISPLAY_TEST_1',playlist};
  const calls=[],ordinary=[],errors=[];
  const V={selectedMonitor:monitor,currentSelection:options.current===undefined?wallpapers[6]:wallpapers[options.current],
    wallpaperConfig:{selectedwallpapers:{}},preview:{play:true},
    promptWallpaperWindowsCompatibility:()=>options.gate||Promise.resolve(),promptWallpaperDependencySubscription:()=>Promise.resolve()};
  const angular={isObject:x=>x!==null&&typeof x==='object',isDefined:x=>x!==undefined,isNumber:x=>typeof x==='number',isString:x=>typeof x==='string',copy:structuredClone};
  const F={callDeferred:(...args)=>{calls.push(structuredClone(args));return Promise.resolve();}};
  const context=vm.createContext({V,angular,F,O:{when:()=>Promise.resolve()},N:[],xt:0,fe:false,m:()=>{},
    l:e=>ordinary.push(e),Xe:()=>Promise.resolve(),console:{error:e=>errors.push(e)}});
  const serializer=script.slice(script.indexOf('function resumePlaylistSettings(e){'),script.indexOf('function Ne(e){'));
  const callbacks=script.slice(script.indexOf('function applyResumePlaylistEntry(e,c){'),script.indexOf(';var St=[]',script.indexOf('function applyResumePlaylistEntry(e,c){'))+1);
  assert.ok(callbacks.endsWith('};'));
  vm.runInContext(serializer+callbacks,context);
  const settle=async()=>{for(let i=0;i<24;i++)await Promise.resolve();};
  return {V,playlist,monitor,wallpapers,calls,ordinary,context,settle,errors};
}

test('only the playlist strip passes an explicit row selection',()=>{
  assert.equal((script.match(/ng-click="callbackPlaylistEntrySelected\(entry,\$index\)"/g)||[]).length,1);
  assert.equal((script.match(/ng-click="callbackWallpaperSelected\(entry.wallpaper\)"/g)||[]).length,0);
  assert.ok(script.includes('V.callbackWallpaperSelected=function(e,resumeSelection)'));
});

test('real click callbacks emit one-shot positions without changing saved settings',async()=>{
  const requests=[];
  for(const position of [1,2,7,10]) {
    const b=browser();b.V.callbackPlaylistEntrySelected(b.playlist.items[position-1],position-1);await b.settle();
    assert.equal(b.calls.length,1);assert.equal(b.ordinary.length,0);
    const [object,method,payload,location]=b.calls[0];
    assert.equal(object,'browseWallpaperObject');assert.equal(method,'selectPlaylist');
    assert.equal(location,b.monitor.location);assert.equal(payload.resumeposition,position);
    assert.equal(Object.hasOwn(payload.settings,'resumeposition'),false);
    assert.equal(payload.items[position-1],b.wallpapers[position-1].file);
    assert.equal(b.V.currentSelection,b.wallpapers[position-1]);
    assert.equal(b.V.wallpaperConfig.selectedwallpapers[location].file,b.wallpapers[position-1].file);
    assert.equal(Object.hasOwn(b.playlist.settings,'resumeposition'),false);
    assert.equal(Object.hasOwn(vm.runInContext('qe(V.selectedMonitor.playlist)',b.context).settings,'resumeposition'),false);
    requests.push(payload);
  }
  const out=process.env.WE_BUILD_OUTPUT||path.resolve(__dirname,'../build');fs.mkdirSync(out,{recursive:true});
  fs.writeFileSync(path.join(out,'ui-selection-requests.json'),JSON.stringify(requests,null,2)+'\n');
});

test('loaded legacy settings drop the old saved selection without changing the input',()=>{
  const b=browser();
  b.playlist.settings.resumeposition=70;
  const saved=vm.runInContext('qe(V.selectedMonitor.playlist)',b.context);
  assert.equal(Object.hasOwn(saved.settings,'resumeposition'),false);
  assert.equal(b.playlist.settings.resumeposition,70);
});

test('clicking the already visible startup WP1 still emits the reset to position 1',async()=>{
  const b=browser({}, {current:0});b.V.callbackPlaylistEntrySelected(b.playlist.items[0],0);await b.settle();
  assert.equal(b.calls[0][2].resumeposition,1);
});

test('duplicate wallpapers retain the clicked row and its preset',async()=>{
  const b=browser();b.playlist.items[5]={wallpaper:b.wallpapers[1],preset:'Second preset'};
  b.V.callbackPlaylistEntrySelected(b.playlist.items[5],5);await b.settle();
  assert.equal(b.calls[0][2].resumeposition,6);
  assert.deepEqual(b.calls[0][2].items[5],{file:'WP_00002',preset:'Second preset'});
});

test('ordinary library selection and disabled or other playlist modes use the original callback',async()=>{
  for(const settings of [{rememberposition:false},{beginfirst:false},{mode:'logon'},{order:'random'}]) {
    const b=browser(settings);b.V.callbackPlaylistEntrySelected(b.playlist.items[1],1);await b.settle();
    assert.deepEqual(b.ordinary,[b.wallpapers[1]]);assert.equal(b.calls.length,0);
  }
  const b=browser();b.V.callbackWallpaperSelected(b.wallpapers[1]);await b.settle();
  assert.deepEqual(b.ordinary,[b.wallpapers[1]]);assert.equal(b.calls.length,0);
});

test('monitor or playlist changes during native compatibility prompts discard a stale click',async()=>{
  for(const change of ['monitor','playlist','row','settings']) {
    let release;const gate=new Promise(resolve=>{release=resolve;});const b=browser({}, {gate});
    b.V.callbackPlaylistEntrySelected(b.playlist.items[1],1);await b.settle();
    if(change==='monitor')b.V.selectedMonitor={...b.monitor,location:'DISPLAY_TEST_2'};
    if(change==='playlist')b.monitor.playlist=structuredClone(b.playlist);
    if(change==='row')b.playlist.items.reverse();
    if(change==='settings')b.playlist.settings.rememberposition=false;
    release();await b.settle();assert.equal(b.calls.length,0);assert.equal(b.ordinary.length,0);
  }
});

test('uninstalled entries never send a position request',async()=>{
  const b=browser();b.wallpapers[1].status='downloadable';
  b.V.callbackPlaylistEntrySelected(b.playlist.items[1],1);await b.settle();
  assert.equal(b.calls.length,0);assert.equal(b.ordinary.length,0);
});
