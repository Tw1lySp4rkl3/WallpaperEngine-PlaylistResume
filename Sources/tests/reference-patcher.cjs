#!/usr/bin/env node
'use strict';
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {execFileSync}=require('node:child_process');
const DEFAULT_ROOT=null;
const BACKUP_NAME='playlist-resume-2.8.42-backup';
const FILES=['wallpaper32.exe','wallpaper64.exe','ui/dist/scripts/scripts.js','PlaylistResume32.dll','PlaylistResume64.dll'];
const R01_HASHES=new Set(['e79fb3f5f6ba6c284bf8edc36ecc3e036a13984b9a93c9fd70111cc71430c08f','8ac79c8dfce46c52db33e6961dca61a4e30e19afcbe5290ce0cda8a0900b36bb']);
const R02_HASHES=new Set(['d2e02e1086e269d8bd3c6a01ba1626e6c6b81bf0c82418b0a8a4008aff457617','ef6091130540f7d5be20b5f0f97273cf44e61ca6e8e389b0ac3ef5fe8df50e4f']);
const hash=data=>crypto.createHash('sha256').update(data).digest('hex');

function loadManifests(directory=path.join(__dirname,'../patches')) {
  const catalog=JSON.parse(fs.readFileSync(path.join(directory,'patches.json'),'utf8'));
  return FILES.map(filename=>{
    const m=catalog.files.find(m=>m.filename===filename);
    if(!m||m.version!=='2.8.42'||m.revision!==catalog.version)throw new Error('Ungueltiges Patchpaket: '+filename);
    return m;
  });
}
function loadLegacy() {
  const releases=JSON.parse(fs.readFileSync(path.join(__dirname,'../patches/legacy.json'),'utf8')).releases;
  return FILES.slice(0,3).map(filename=>releases.find(r=>r.version==='R02').files.find(m=>m.filename===filename));
}
function loadR03() {
  return JSON.parse(fs.readFileSync(path.join(__dirname,'../patches/legacy.json'),'utf8')).releases.find(r=>r.version==='R03').files;
}
function classify(data,m) {
  if(data===null)return m.kind==='new'?'absent':'unknown';
  const sha=hash(data);
  if(sha===m.patched_sha256&&data.length===m.patched_size)return 'patched';
  if(m.original_sha256&&sha===m.original_sha256&&data.length===m.original_size)return 'original';
  if(R02_HASHES.has(sha))return 'R02';
  if(loadR03().some(old=>old.filename===m.filename&&old.patched_sha256===sha&&old.patched_size===data.length))return 'R03';
  if(loadLegacy().some(old=>old.filename===m.filename&&old.patched_sha256===sha&&old.patched_size===data.length))return 'R02';
  if(R01_HASHES.has(sha))return 'R01';
  return 'unknown';
}
function transform(data,m,direction) {
  const forward=direction==='apply';
  if(m.kind==='new') {
    const contents=Buffer.from(m.contents_hex,'hex');
    if(contents.length!==m.patched_size||hash(contents)!==m.patched_sha256)throw new Error('Ungueltiger DLL-Inhalt: '+m.filename);
    if(forward) {
      if(data!==null)throw new Error('Neue DLL hat unerwartete Ausgangsdaten.');
      return contents;
    }
    if(!data||hash(data)!==m.patched_sha256)throw new Error('DLL fuer Ruecknahme stimmt nicht.');
    return null;
  }
  const sourceHash=forward?m.original_sha256:m.patched_sha256;
  const targetHash=forward?m.patched_sha256:m.original_sha256;
  const sourceSize=forward?m.original_size:m.patched_size;
  if(!data||data.length!==sourceSize||hash(data)!==sourceHash)throw new Error('SHA-256 stimmt nicht: '+m.filename);
  let result;
  if(m.kind==='text') {
    let s=data.toString('utf8');
    for(const r of (forward?m.replacements:[...m.replacements].reverse())) {
      const before=forward?r.before:r.after,after=forward?r.after:r.before;
      if(typeof before!=='string'||!before||typeof after!=='string'||s.split(before).length!==2)throw new Error('UI-Patchbereich stimmt nicht.');
      s=s.replace(before,()=>after);
    }
    result=Buffer.from(s,'utf8');
  } else if(m.kind==='pe') {
    const append=Buffer.from(m.append_hex,'hex');
    if(m.original_size+append.length!==m.patched_size)throw new Error('Ungueltige PE-Laenge.');
    if(!forward&&!data.subarray(m.original_size).equals(append))throw new Error('PE-Anhang stimmt nicht.');
    result=forward?Buffer.concat([data,append]):Buffer.from(data.subarray(0,m.original_size));
    const ranges=[];
    for(const c of m.changes) {
      const before=Buffer.from(forward?c.before:c.after,'hex'),after=Buffer.from(forward?c.after:c.before,'hex');
      const at=c.offset;
      if(!Number.isSafeInteger(at)||at<0||!before.length||before.length!==after.length||at+before.length>m.original_size||
         ranges.some(([a,b])=>at<b&&at+before.length>a))throw new Error('Ungueltiger Patchbereich: '+c.label);
      if(!data.subarray(at,at+before.length).equals(before))throw new Error('Originalbytes stimmen nicht: '+c.label);
      ranges.push([at,at+before.length]);after.copy(result,at);
    }
  } else throw new Error('Unbekanntes Patchformat.');
  if(hash(result)!==targetHash)throw new Error('Ergebnispruefung fehlgeschlagen: '+m.filename);
  return result;
}
function assertStopped() {
  if(process.platform!=='win32')return;
  let output;
  try {output=execFileSync('tasklist.exe',['/FO','CSV','/NH'],{encoding:'utf8',windowsHide:true,timeout:10000});}
  catch {throw new Error('Prozesspruefung fehlgeschlagen. Wallpaper Engine vollstaendig beenden.');}
  const names=output.split(/\r?\n/).map(s=>/^"([^"]+)"/.exec(s)?.[1]?.toLowerCase());
  if(['wallpaper32.exe','wallpaper64.exe','wallpaperui.exe'].some(s=>names.includes(s)))throw new Error('Wallpaper Engine laeuft noch. Ueber das Taskleistensymbol vollstaendig beenden.');
}
function readOrNull(file){return fs.existsSync(file)?fs.readFileSync(file):null;}
function same(data,expected){return data===null?expected===null:expected!==null&&hash(data)===hash(expected);}
function originalBytes(job,legacy) {
  if(job.manifest.kind==='new')return null;
  if(job.state==='original')return job.before;
  if(job.state==='R02'||job.state==='R03') {
    const old=(job.state==='R03'?loadR03():legacy).find(m=>m.filename===job.manifest.filename);
    if(!old)throw new Error('Alte Ruecknahme fehlt: '+job.manifest.filename);
    return transform(job.before,old,'restore');
  }
  return transform(job.before,job.manifest,'restore');
}
function saveBackups(root,jobs,legacy) {
  const backup=path.join(root,BACKUP_NAME);
  const originals=jobs.map(job=>({job,data:originalBytes(job,legacy)})).filter(x=>x.data!==null);
  for(const {job,data} of originals) {
    const dest=path.join(backup,job.manifest.filename),old=readOrNull(dest);
    if(old!==null&&!same(old,data))throw new Error('Vorhandene Sicherung ist veraendert: '+dest);
  }
  fs.mkdirSync(backup,{recursive:true});
  for(const {job,data} of originals) {
    const dest=path.join(backup,job.manifest.filename);
    fs.mkdirSync(path.dirname(dest),{recursive:true});if(!fs.existsSync(dest))fs.writeFileSync(dest,data,{flag:'wx'});
  }
  for(const relative of ['config.json','bin/playliststate.bin','bin/playliststatetime.bin','bin/pi-playlist-resume-r03.bin',
                         'bin/playlist-resume.bin','bin/pi-playlist-resume-r03.log','bin/playlist-resume.log',
                         'PiPlaylistResume32.dll','PiPlaylistResume64.dll']) {
    const src=path.join(root,relative),dest=path.join(backup,relative);
    if(fs.existsSync(src)&&!fs.existsSync(dest)){fs.mkdirSync(path.dirname(dest),{recursive:true});fs.copyFileSync(src,dest,fs.constants.COPYFILE_EXCL);}
  }
  return backup;
}

function detectRoot() {
  const libraries=[];
  if(process.platform==='win32') {
    try {
      const text=execFileSync('reg.exe',['query','HKCU\\Software\\Valve\\Steam','/v','SteamPath'],{encoding:'utf8',windowsHide:true,timeout:10000});
      const found=/SteamPath\s+REG_SZ\s+(.+)/i.exec(text);if(found)libraries.push(found[1].trim());
    }catch{}
    for(const base of [process.env['ProgramFiles(x86)'],process.env.ProgramFiles])if(base)libraries.push(path.join(base,'Steam'));
  }
  for(const library of [...libraries]) {
    const file=path.join(library,'steamapps','libraryfolders.vdf');
    if(fs.existsSync(file))for(const match of fs.readFileSync(file,'utf8').matchAll(/"path"\s+"((?:\\.|[^"\\])*)"/g))
      libraries.push(match[1].replace(/\\\\/g,'\\'));
  }
  for(const root of [process.cwd(),...libraries.map(p=>path.join(p,'steamapps','common','wallpaper_engine'))])
    if(fs.existsSync(path.join(root,'wallpaper64.exe'))&&fs.existsSync(path.join(root,'ui','dist','scripts','scripts.js')))return root;
  return null;
}

function retiredFiles(root) {
  return loadR03().filter(m=>m.kind==='new').map(manifest=>{
    const target=path.join(root,manifest.filename),before=readOrNull(target);
    if(before!==null&&(hash(before)!==manifest.patched_sha256||before.length!==manifest.patched_size))
      throw new Error('Unbekannte alte DLL: '+manifest.filename+'. Keine Aenderung vorgenommen.');
    return {manifest,target,before,after:null,retired:true};
  });
}

function cacheMigration(root) {
  const target=path.join(root,'bin','playlist-resume.bin'),old=path.join(root,'bin','pi-playlist-resume-r03.bin');
  const jobs=[];
  if(fs.existsSync(old)) {
    const before=fs.readFileSync(old);resumeState(before);
    if(!fs.existsSync(target)) {
      const after=Buffer.from(before);after.write('WPRS0001',0,'ascii');
      jobs.push({manifest:{filename:'bin/playlist-resume.bin',kind:'cache'},target,before:null,after});
    } else resumeState(fs.readFileSync(target));
    jobs.push({manifest:{filename:'bin/pi-playlist-resume-r03.bin',kind:'retired-state'},target:old,before,after:null,retired:true});
  }
  const oldLog=path.join(root,'bin','pi-playlist-resume-r03.log'),newLog=path.join(root,'bin','playlist-resume.log');
  if(fs.existsSync(oldLog)) {
    const before=fs.readFileSync(oldLog);
    if(!fs.existsSync(newLog))jobs.push({manifest:{filename:'bin/playlist-resume.log',kind:'log'},target:newLog,before:null,after:before});
    jobs.push({manifest:{filename:'bin/pi-playlist-resume-r03.log',kind:'retired-log'},target:oldLog,before,after:null,retired:true});
  }
  return jobs;
}

function crc32(data) {
  let crc=0xffffffff;
  for(const byte of data){crc^=byte;for(let j=0;j<8;j++)crc=(crc>>>1)^(0xedb88320&-(crc&1));}
  return (~crc)>>>0;
}
function resumeState(data) {
  if(data.length<16||!['WPRS0001','PIRS0003'].includes(data.toString('ascii',0,8)))throw new Error('Unbekanntes Positionsformat.');
  const n=data.readUInt32LE(8);
  if(n>512||data.length!==16+32*n||crc32(data.subarray(16))!==data.readUInt32LE(12))throw new Error('Positionsspeicher ist beschaedigt oder unvollstaendig.');
  const records=[];
  for(let i=0;i<n;i++) {
    const p=16+32*i,a=data.readBigUInt64LE(p),b=data.readBigUInt64LE(p+8),count=data.readUInt32LE(p+16),index=data.readUInt32LE(p+20);
    if(!count||count>32768||index>=count)throw new Error('Ungueltiger Positionseintrag.');
    records.push({key:a.toString(16).padStart(16,'0')+b.toString(16).padStart(16,'0'),count,position:index+1});
  }
  return records;
}
function playlistKey(monitor,playlist) {
  const mask=0xffffffffffffffffn;let a=14695981039346656037n,b=7809847782465536322n;
  function byte(v){a=((a^BigInt(v))*1099511628211n)&mask;b=((b^BigInt(v))*14029467366897019727n)&mask;}
  function number(v){for(let i=0;i<4;i++)byte((v>>>(8*i))&255);}
  function string(s){const buf=Buffer.from(s,'utf8');number(buf.length);for(const v of buf)byte(v);}
  string(monitor);number(playlist.items.length);
  for(const item of playlist.items){string(typeof item==='string'?item:item.file);string(typeof item==='string'?'':item.preset||'');}
  return a.toString(16).padStart(16,'0')+b.toString(16).padStart(16,'0');
}
function playlistState(data) {
  let offset=0;
  function n(){if(offset+4>data.length)throw new Error('Zustandsdatei abgeschnitten.');const v=data.readUInt32LE(offset);offset+=4;return v;}
  function s(){const len=n();if(len>1048576||offset+len>data.length)throw new Error('Ungueltige Zeichenfolge im Playlist-Zustand.');const v=data.toString('utf8',offset,offset+len);offset+=len;return v;}
  if(s()!=='PLPV0005')throw new Error('Unbekanntes natives Playlist-Format.');
  const groups=n(),records=[];if(groups>64)throw new Error('Zu viele Zustandsgruppen.');
  for(let i=0;i<groups;i++) {
    const group=s(),count=n();if(count>64)throw new Error('Zu viele Monitore.');
    for(let j=0;j<count;j++) {
      const monitor=s(),checkpoint=n();s();s();const items=n();if(items>32768)throw new Error('Zu viele Eintraege.');
      for(let k=0;k<items;k++){s();s();}records.push({group,monitor,checkpoint});
    }
  }
  if(offset!==data.length)throw new Error('Unerwartete Restdaten.');return records;
}
function diagnostics(root,log) {
  log('Installationsordner: '+root);
  let records=[],native=[];
  const normal=path.join(root,'bin','playlist-resume.bin');
  const cache=fs.existsSync(normal)?normal:path.join(root,'bin','pi-playlist-resume-r03.bin');
  if(fs.existsSync(cache))try{records=resumeState(fs.readFileSync(cache));log('Positionsspeicher: '+records.length+' gepruefte Eintraege.');}catch(e){log(e.message);}
  else log('Positionsspeicher: noch kein regulaeres Wallpaper gespeichert.');
  const state=path.join(root,'bin','playliststate.bin');
  if(fs.existsSync(state))try{native=playlistState(fs.readFileSync(state));}catch(e){log('Nativer Zustand: '+e.message);}
  const configFile=path.join(root,'config.json');
  if(fs.existsSync(configFile))try {
    const config=JSON.parse(fs.readFileSync(configFile,'utf8'));let counter=0;
    for(const user of Object.values(config)) {
      const selected=user?.general?.wallpaperconfig?.selectedwallpapers;if(!selected)continue;
      for(const [monitor,entry] of Object.entries(selected)) {
        const p=entry?.playlist,s=p?.settings;if(!s||!Array.isArray(p.items))continue;
        const remembered=records.find(r=>r.key===playlistKey(monitor,p));
        const old=native.find(r=>r.group==='wallpaperconfig'&&r.monitor===monitor);
        const yes=v=>v===true?'an':'aus';
        log('Konfiguration '+(++counter)+' ('+(p.name||'Playlist')+'): merken='+yes(s.rememberposition)+', erster='+yes(s.beginfirst)+
            ', nurStart='+yes(s.playintro)+', Position='+(remembered?remembered.position:'keine')+
            ', nativer Zaehler='+(old?old.checkpoint:'keiner'));
      }
    }
  }catch(e){log('Konfiguration nicht lesbar: '+e.message);}
  const trace=path.join(root,'bin','playlist-resume.log');
  if(fs.existsSync(trace)){log('Letzte Playlist-Ereignisse:');for(const line of fs.readFileSync(trace,'utf8').trim().split(/\r?\n/).slice(-12))log(line);}
  if(process.platform==='win32')try {
    const script="$p=@(Get-CimInstance Win32_Process | Where-Object {$_.Name -in @('wallpaper32.exe','wallpaper64.exe','wallpaperui.exe')} | Select-Object Name,ProcessId,ExecutablePath); ConvertTo-Json -InputObject $p -Compress";
    log('Laufende Prozesse: '+execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{encoding:'utf8',windowsHide:true,timeout:10000}).trim());
  }catch{log('Prozesspfade konnten nicht ausgelesen werden.');}
}

function run(action,root=DEFAULT_ROOT,options={}) {
  if(!['status','apply','restore'].includes(action))throw new Error('Aktion: status, apply oder restore.');
  root=root||detectRoot();
  if(!root)throw new Error('Wallpaper-Engine-Ordner nicht gefunden. INSTALL.cmd "D:\\SteamLibrary\\steamapps\\common\\wallpaper_engine" verwenden; fuer STATUS/RESTORE denselben Ordner angeben.');
  root=path.resolve(root);const manifests=options.manifests||loadManifests(),log=options.log||console.log;
  const inventory=manifests.map(manifest=>{
    const target=path.join(root,manifest.filename),before=readOrNull(target),state=classify(before,manifest);
    if(state==='unknown')throw new Error('Unbekannte oder aktualisierte Datei: '+manifest.filename+'. Keine Aenderung vorgenommen.');
    return {manifest,target,before,state};
  });
  const retired=retiredFiles(root);
  if(action==='status') {
    log('Wallpaper Engine 2.8.42 / Playlist Resume / R04');
    inventory.forEach(j=>log(j.manifest.filename+': '+(j.state==='patched'?'R04 bereit':j.state)));
    retired.filter(j=>j.before!==null).forEach(j=>log(j.manifest.filename+': bekannte R03-Datei; wird beim Aktualisieren entfernt.'));
    if(options.diagnostics!==false)diagnostics(root,log);
    return inventory.map(j=>({filename:j.manifest.filename,state:j.state}));
  }
  if(inventory.some(j=>j.state==='R01'))throw new Error('R01 ist noch installiert. Zuerst dessen RESTORE.cmd ausfuehren. R02 und R03 koennen direkt aktualisiert werden.');
  assertStopped();
  const legacy=options.legacy||loadLegacy();
  const jobs=inventory.filter(j=>j.state!==(action==='apply'?'patched':j.manifest.kind==='new'?'absent':'original')).map(j=>{
    const original=originalBytes(j,legacy);
    return {...j,after:action==='apply'?transform(original,j.manifest,'apply'):original};
  });
  jobs.push(...retired.filter(j=>j.before!==null));
  if(action==='apply')jobs.push(...cacheMigration(root));
  if(!jobs.length){log(action==='apply'?'R04 ist bereits installiert.':'Originaldateien sind bereits vorhanden.');return [];}
  // Install dependencies first; restore their original users before deleting DLLs.
  const priority=j=>j.retired?3:j.manifest.kind==='new'?(action==='apply'?0:2):j.manifest.kind==='cache'?1:(action==='apply'?2:0);
  jobs.sort((a,b)=>priority(a)-priority(b));
  const backup=saveBackups(root,inventory,legacy),committed=[],temporary=[];
  let failure;
  try {
    for(const j of jobs)if(j.after!==null) {
      j.temp=j.target+'.playlist-resume-'+crypto.randomUUID()+'.tmp';temporary.push(j.temp);
      fs.writeFileSync(j.temp,j.after,{flag:'wx'});
      if(!same(fs.readFileSync(j.temp),j.after))throw new Error('Temporaere Datei konnte nicht verifiziert werden.');
    }
    for(const j of jobs) {
      if(!same(readOrNull(j.target),j.before))throw new Error('Datei waehrend Installation geaendert: '+j.manifest.filename);
      if(j.after===null)fs.unlinkSync(j.target);else fs.renameSync(j.temp,j.target);
      committed.push(j);
      if(!same(readOrNull(j.target),j.after))throw new Error('Pruefung nach Ersetzen fehlgeschlagen.');
    }
  }catch(error) {
    const errors=[];
    for(const j of committed.reverse())try {
      if(!same(readOrNull(j.target),j.after))throw new Error('Datei zwischenzeitlich geaendert');
      if(j.before===null)fs.unlinkSync(j.target);
      else {
        const temp=j.target+'.playlist-resume-rollback-'+crypto.randomUUID()+'.tmp';temporary.push(temp);
        fs.writeFileSync(temp,j.before,{flag:'wx'});fs.renameSync(temp,j.target);
      }
    }catch(e){errors.push(j.manifest.filename+': '+e.message);}
    failure=new Error(error.message+(errors.length?'\nRuecknahme unvollstaendig: '+errors.join('; ')+'\nSicherung: '+backup:'\nBereits ersetzte Dateien wurden zurueckgesetzt.'));
  }finally {
    for(const temp of temporary)if(fs.existsSync(temp))try{fs.unlinkSync(temp);}catch{}
  }
  if(failure)throw failure;
  log(action==='apply'?'Playlist Resume R04 installiert.':'Original-EXEs/UI wiederhergestellt; bekannte Erweiterungs-DLLs entfernt.');
  log('Sicherung: '+backup);
  if(action==='apply') {
    log('Playlist: Timer, sortiert, erster Hintergrund AN, Playlist-Position merken AN, nur beim Start zeigen AUS.');
    log('Klick auf einen Eintrag im Playlist-Streifen setzt den Ausgangspunkt. Klick auf WP2: naechster Wechsel zu WP3.');
    log('Programmstart mit gespeichertem WP4: WP1, danach WP4 und WP5.');
    if(jobs.some(j=>j.manifest.kind==='cache'))log('Vorhandene R03-Positionen wurden uebernommen. Die alte Datei liegt im Sicherungsordner.');
  }
  return jobs.map(j=>({filename:j.manifest.filename,state:j.after===null?'absent':action==='apply'?'patched':'original'}));
}
module.exports={hash,loadManifests,loadLegacy,loadR03,classify,transform,run,playlistState,resumeState,playlistKey,crc32,detectRoot,DEFAULT_ROOT,BACKUP_NAME};
if(require.main===module)try{run(process.argv[2]||'status',process.argv[3]||DEFAULT_ROOT);}catch(e){console.error('\nFEHLER: '+e.message);process.exitCode=1;}
