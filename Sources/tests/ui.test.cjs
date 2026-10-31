'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {transform,loadManifests}=require('./reference-patcher.cjs');
const originals=process.env.WE_ORIGINALS||path.resolve(__dirname,'../upload');
const manifest=loadManifests().find(m=>m.kind==='text');
const original=fs.readFileSync(path.join(originals,'scripts.js'));
const patched=transform(original,manifest,'apply').toString('utf8');

function template(name) {
  const marker='e.put("'+name+'",';
  const start=patched.indexOf(marker)+marker.length;
  assert.ok(start>=marker.length);
  const end=patched.indexOf('),e.put(',start);
  return vm.runInNewContext(patched.slice(start,end));
}

function controller(settings) {
  const watches=[];let closed;
  const scope={$watch:(name,fn)=>watches.push({name,fn}),$broadcast:()=>{}};
  const angular={copy:x=>structuredClone(x),isString:x=>typeof x==='string',isNumber:x=>typeof x==='number',isArray:Array.isArray};
  const start=patched.indexOf('angular.module("wallpaperbrowserApp").controller("BrowsePlaylistSettingsModalCtrl",');
  const end=patched.indexOf(',window.effectListModalGalleryMode=',start);
  let constructor;
  angular.module=()=>({controller:(name,dependencies)=>{constructor=dependencies.at(-1);}});
  vm.runInNewContext(patched.slice(start,end),{angular});
  assert.equal(typeof constructor,'function');
  const utils={getTransitionOptions:()=>[],getTransitionButtons:()=>[],configureTransitionSlider:()=>({}),
               transitionPoolSelectAll:()=>{},transitionPoolToggle:()=>{}};
  constructor({when:()=>Promise.resolve()},fn=>fn(),scope,{close:x=>{closed=structuredClone(x);},dismiss:()=>{}},
              {open:()=>Promise.resolve()},utils,{settings,items:[],fnPreviewTransition:()=>{}});
  const digest=()=>{for(const w of watches){let v=scope;for(const key of w.name.split('.'))v=v?.[key];w.fn(v);}};
  digest();
  return {scope,digest,get closed(){return closed;}};
}

const base={mode:'timer',order:'sorted',delay:30,beginfirst:true,playintro:false};

test('the complete patched UI script parses and restores byte-for-byte',()=>{
  new vm.Script(patched);
  assert.deepEqual(transform(Buffer.from(patched),manifest,'restore'),original);
});

test('new checkbox binds to rememberposition in the existing playlist modal',()=>{
  const html=template('views/modals/browseplaylistsettingsmodal.html');
  assert.equal((html.match(/id="inputRememberPosition"/g)||[]).length,1);
  assert.match(html,/>Playlist-Position merken<\/label>/);
  assert.match(html,/<checkbox id="inputRememberPosition"[^>]*cb-checked="settings.rememberposition"/);
  assert.match(html,/<checkbox id="inputRememberPosition"[^>]*cb-disabled="!settings.beginfirst \|\| settings.order != 'sorted'"/);
  assert.match(html,/<checkbox id="inputPlayIntro"[^>]*cb-disabled="[^"]*settings.rememberposition"/);
});

test('label toggle enables remembering and clears the native intro-only setting',()=>{
  const c=controller({...base,playintro:true});
  assert.equal(c.scope.settings.rememberposition,false);
  c.scope.toggleRememberPosition();c.digest();
  assert.equal(c.scope.settings.rememberposition,true);
  assert.equal(c.scope.settings.playintro,false);
  c.scope.togglePlayIntro();c.digest();
  assert.equal(c.scope.settings.playintro,false);
});

test('checkbox binding and settings copy retain the new boolean for save/reopen',async()=>{
  const c=controller({...base,playintro:true});
  // cb-checked is the native checkbox directive's two-way binding.
  c.scope.settings.rememberposition=true;c.digest();
  c.scope.ok();await Promise.resolve();
  assert.equal(c.closed.rememberposition,true);
  assert.equal(c.closed.playintro,false);
  const reopened=controller(JSON.parse(JSON.stringify(c.closed)));
  assert.equal(reopened.scope.settings.rememberposition,true);
  reopened.scope.toggleRememberPosition();reopened.digest();
  assert.equal(reopened.scope.settings.rememberposition,false);
});

test('the new label cannot enable the feature for a random list or without first-start',()=>{
  for (const settings of [{...base,order:'random'},{...base,beginfirst:false},{...base,mode:'logon'}]) {
    const c=controller(settings);c.scope.toggleRememberPosition();c.digest();
    assert.equal(c.scope.settings.rememberposition,false);
  }
});

test('native intro-only option still works when remembering is off',()=>{
  const c=controller(base);c.scope.togglePlayIntro();
  assert.equal(c.scope.settings.playintro,true);
});

test('UI serialization passes arbitrary playlist settings rather than a native-key whitelist',()=>{
  assert.match(patched,/function qe\(e\)\{return\{settings:angular.copy\(e.settings\)/);
  assert.match(patched,/angular.merge\(V.selectedMonitor.playlist.settings,e\)/);
  const c=controller({...base,rememberposition:true,customExistingSetting:'keep'});
  assert.equal(c.scope.settings.customExistingSetting,'keep');
});
