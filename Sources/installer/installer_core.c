/* Portable installation engine. The Windows frontend supplies only filesystem,
 * allocation, process checks and log output. All payloads are compiled in. */
#include "installer_core.h"
#define MAX_JOBS 16
#define MAX_DATA (64u*1024u*1024u)
#define RECEIPT "bin/playlist-resume-install.json"
#define BACKUP "playlist-resume-backup/"

static size_t length(const char *s){size_t n=0;while(s[n])n++;return n;}
static void copy(void *d,const void *s,size_t n){unsigned char *a=d;const unsigned char *b=s;for(size_t i=0;i<n;i++)a[i]=b[i];}
static int equal(const void *a,const void *b,size_t n){const unsigned char *x=a,*y=b;for(size_t i=0;i<n;i++)if(x[i]!=y[i])return 0;return 1;}
static int string_equal(const char *a,const char *b){size_t n=length(a);return n==length(b)&&equal(a,b,n);}
static void zero(void *p,size_t n){unsigned char *b=p;for(size_t i=0;i<n;i++)b[i]=0;}
static int append(char *dest,size_t cap,const char *s){size_t n=length(dest),m=length(s);if(n+m>=cap)return 0;copy(dest+n,s,m+1);return 1;}
static void text(char *dest,size_t cap,const char *s){dest[0]=0;append(dest,cap,s);}
static void message(const PrFS *fs,const char *prefix,const char *path){char b[512];text(b,sizeof b,prefix);if(path)append(b,sizeof b,path);if(fs->log)fs->log(fs->context,b);}
static void drop(PrBuffer *b){if(b->data)pr_free(b->data);zero(b,sizeof *b);}
static int clone(PrBuffer *dest,const unsigned char *data,size_t n){
    zero(dest,sizeof *dest);if(n>MAX_DATA)return 0;
    dest->data=pr_alloc(n?n:1);if(!dest->data)return 0;copy(dest->data,data,n);dest->size=n;dest->exists=1;return 1;
}
static int same(const PrBuffer *a,const PrBuffer *b){return a->exists==b->exists&&(!a->exists||(a->size==b->size&&equal(a->data,b->data,a->size)));}
static int digest(const PrBuffer *b,size_t size,const unsigned char *expected){
    if(!b->exists||b->size!=size||!expected)return 0;
    unsigned char h[32];pr_hash(b->data,b->size,h);return equal(h,expected,32);
}

int pr_transform(const PrBuffer *source,const PrManifest *m,int forward,PrBuffer *out){
    zero(out,sizeof *out);
    if(m->kind==2){
        PrBuffer payload={(unsigned char*)m->contents.data,m->contents.size,1};
        if(!digest(&payload,m->patched_size,m->patched_hash))return 0;
        if(forward)return !source->exists&&clone(out,payload.data,payload.size);
        return digest(source,m->patched_size,m->patched_hash);
    }
    if(!digest(source,forward?m->original_size:m->patched_size,forward?m->original_hash:m->patched_hash))return 0;
    if(m->kind==0){
        if(m->original_size+m->append.size!=m->patched_size)return 0;
        if(!forward&&!equal(source->data+m->original_size,m->append.data,m->append.size))return 0;
        size_t n=forward?m->patched_size:m->original_size;
        out->data=pr_alloc(n?n:1);if(!out->data)return 0;out->size=n;out->exists=1;
        copy(out->data,source->data,m->original_size);
        if(forward)copy(out->data+m->original_size,m->append.data,m->append.size);
        for(size_t i=0;i<m->change_count;i++){
            const PrChange *c=m->changes+i;PrSpan before=forward?c->before:c->after,after=forward?c->after:c->before;
            if(!before.size||before.size!=after.size||c->offset>m->original_size||before.size>m->original_size-c->offset)goto fail;
            for(size_t j=0;j<i;j++){
                const PrChange *previous=m->changes+j;
                if(c->offset<previous->offset+previous->before.size&&previous->offset<c->offset+before.size)goto fail;
            }
            if(!equal(source->data+c->offset,before.data,before.size))goto fail;
            copy(out->data+c->offset,after.data,after.size);
        }
    }else if(m->kind==1){
        if(!clone(out,source->data,source->size))return 0;
        for(size_t i=0;i<m->replacement_count;i++){
            const PrReplacement *r=m->replacements+(forward?i:m->replacement_count-1-i);
            PrSpan before=forward?r->before:r->after,after=forward?r->after:r->before;
            size_t at=0,hits=0;if(!before.size||before.size>out->size)goto fail;
            for(size_t j=0;j<=out->size-before.size;j++)if(equal(out->data+j,before.data,before.size)){at=j;hits++;}
            if(hits!=1||after.size>MAX_DATA||out->size-before.size>MAX_DATA-after.size)goto fail;
            PrBuffer next;size_t n=out->size-before.size+after.size;
            next.data=pr_alloc(n?n:1);if(!next.data)goto fail;next.size=n;next.exists=1;
            copy(next.data,out->data,at);copy(next.data+at,after.data,after.size);
            copy(next.data+at+after.size,out->data+at+before.size,out->size-at-before.size);
            drop(out);*out=next;
        }
    }else return 0;
    if(!digest(out,forward?m->patched_size:m->original_size,forward?m->patched_hash:m->original_hash))goto fail;
    return 1;
  fail:drop(out);return 0;
}

typedef struct {PrBuffer files[8];const PrManifest *matched[7];int original[7];} Inventory;
static void inventory_drop(Inventory *i){for(unsigned n=0;n<8;n++)drop(i->files+n);}
static int receipt_matches(const PrBuffer *b,PrSpan expected){
    return expected.size?(b->exists&&b->size==expected.size&&equal(b->data,expected.data,expected.size)):!b->exists;
}
static int read_inventory(const PrFS *fs,Inventory *i,PrStatus *status){
    zero(i,sizeof *i);zero(status,sizeof *status);
    for(unsigned n=0;n<8;n++){
        const char *path=n==7?RECEIPT:pr_paths[n];
        if(!fs->read(fs->context,path,i->files+n)){
            text(status->label,sizeof status->label,"Dateien konnten nicht gelesen werden");
            text(status->detail,sizeof status->detail,path);return 0;
        }
        if(n<3&&i->files[n].exists)status->found=1;
    }
    if(!status->found){text(status->label,sizeof status->label,"Nicht gefunden");text(status->detail,sizeof status->detail,"Bitte den Wallpaper-Engine-Installationsordner auswählen.");return 0;}
    for(unsigned n=0;n<7;n++){
        PrBuffer *b=i->files+n;
        if(n<3&&digest(b,pr_current[n]->original_size,pr_current[n]->original_hash)){i->original[n]=1;continue;}
        if(n>=3&&!b->exists){i->original[n]=1;continue;}
        for(size_t k=0;k<pr_known_count;k++){
            const PrManifest *m=pr_known[k];
            if(string_equal(m->filename,pr_paths[n])&&digest(b,m->patched_size,m->patched_hash)){i->matched[n]=m;break;}
        }
        if(!i->matched[n]){
            text(status->label,sizeof status->label,"Unbekannte oder nicht unterstützte Dateien");
            text(status->detail,sizeof status->detail,pr_paths[n]);return 0;
        }
    }
    PrSpan receipt={pr_receipt,pr_receipt_size};int current_receipt=receipt_matches(i->files+7,receipt);
    int known_receipt=!i->files[7].exists||current_receipt;
    for(size_t r=0;r<pr_legacy_release_count;r++)
        if(receipt_matches(i->files+7,pr_legacy_releases[r].receipt))known_receipt=1;
    if(!known_receipt){
        text(status->label,sizeof status->label,"Unbekannte Mod-Installationsinfo");
        text(status->detail,sizeof status->detail,"Die vorhandene Installationsinfo gehört nicht zu dieser Ausgabe.");return 0;
    }
    status->supported=1;status->can_install=1;
    int modified=i->files[7].exists;
    for(unsigned n=0;n<7;n++)if(!i->original[n])modified=1;
    status->can_restore=modified;
    int current=1;
    for(unsigned n=0;n<5;n++)if(!digest(i->files+n,pr_current[n]->patched_size,pr_current[n]->patched_hash))current=0;
    if(i->files[5].exists||i->files[6].exists)current=0;
    if(current&&current_receipt){
        status->version=1;text(status->label,sizeof status->label,"Installiert – v");
        append(status->label,sizeof status->label,pr_project_version);
    }else if(!modified){status->version=0;text(status->label,sizeof status->label,"Nicht installiert");}
    else{
        status->version=6;text(status->label,sizeof status->label,"Unvollständige Installation – Reparatur möglich");
        for(size_t r=0;r<pr_legacy_release_count;r++){
            const PrLegacyRelease *release=pr_legacy_releases+r;
            if(!receipt_matches(i->files+7,release->receipt))continue;
            int all=1;
            for(unsigned n=0;n<7;n++){
                const PrManifest *expected=0;
                for(size_t k=0;k<release->file_count;k++){
                    const PrManifest *m=release->files[k];
                    if(string_equal(m->filename,pr_paths[n])){expected=m;break;}
                }
                if(expected){if(!digest(i->files+n,expected->patched_size,expected->patched_hash))all=0;}
                else if(!i->original[n])all=0;
            }
            if(all){
                status->version=release->release;
                text(status->label,sizeof status->label,release->preview?"Installiert – Vorabversion ":"Installiert – v");
                append(status->label,sizeof status->label,release->version);break;
            }
        }
    }
    text(status->detail,sizeof status->detail,"Wallpaper Engine 2.8.42 (Steam): geprüfte Dateien erkannt.");return 1;
}
int pr_status(const PrFS *fs,PrStatus *status){Inventory i;int result=read_inventory(fs,&i,status);inventory_drop(&i);return result;}

typedef struct {const char *path;PrBuffer before,after;int own_before,rank,committed,staged;char temp[160];} Job;
typedef struct {Job jobs[MAX_JOBS];unsigned count;} Plan;
static int add(Plan *p,const char *path,PrBuffer before,PrBuffer after,int owns_before,int rank){
    if(same(&before,&after)){if(owns_before)drop(&before);drop(&after);return 1;}
    if(p->count==MAX_JOBS){if(owns_before)drop(&before);drop(&after);return 0;}
    Job *j=p->jobs+p->count++;zero(j,sizeof *j);j->path=path;j->before=before;j->after=after;j->own_before=owns_before;j->rank=rank;return 1;
}
static void plan_drop(Plan *p){for(unsigned i=0;i<p->count;i++){if(p->jobs[i].own_before)drop(&p->jobs[i].before);drop(&p->jobs[i].after);}pr_free(p);}
static uint32_t u32(const unsigned char *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static int valid_cache(const PrBuffer *b){
    if(!b->exists||b->size<16||(!equal(b->data,"PIRS0003",8)&&!equal(b->data,"WPRS0001",8)))return 0;
    uint32_t count=u32(b->data+8),crc=~0u;if(count>512||b->size!=16+32*(size_t)count)return 0;
    for(size_t i=16;i<b->size;i++){crc^=b->data[i];for(unsigned k=0;k<8;k++)crc=(crc>>1)^(0xedb88320u&(0u-(crc&1)));}
    if(~crc!=u32(b->data+12))return 0;
    for(unsigned i=0;i<count;i++){uint32_t n=u32(b->data+16+32*i+16),index=u32(b->data+16+32*i+20);if(!n||n>32768||index>=n)return 0;}
    return 1;
}
static int migrate_pair(const PrFS *fs,Plan *p,const char *old,const char *target,int cache){
    PrBuffer source={0},existing={0},after={0},empty={0};
    if(!fs->read(fs->context,old,&source))return 0;
    if(!source.exists)return 1;
    if(!fs->read(fs->context,target,&existing))goto fail;
    if(cache&&(!valid_cache(&source)||(existing.exists&&!valid_cache(&existing)))){message(fs,"Beschädigter Positionsspeicher: ",old);goto fail;}
    if(!existing.exists){
        if(!clone(&after,source.data,source.size))goto fail;
        if(cache)copy(after.data,"WPRS0001",8);
        if(!add(p,target,empty,after,0,1)){zero(&after,sizeof after);goto fail;}
        zero(&after,sizeof after);
    }
    drop(&existing);
    if(!add(p,old,source,empty,1,3)){zero(&source,sizeof source);return 0;}
    return 1;
  fail:drop(&source);drop(&existing);drop(&after);return 0;
}
static int expected(const PrFS *fs,const char *path,const PrBuffer *b){PrBuffer current={0};int ok=fs->read(fs->context,path,&current)&&same(&current,b);drop(&current);return ok;}
static int backup_file(const PrFS *fs,const char *path,const PrBuffer *original,int strict){
    char target[256];text(target,sizeof target,BACKUP);if(!append(target,sizeof target,path))return 0;
    PrBuffer existing={0};if(!fs->read(fs->context,target,&existing))return 0;
    if(existing.exists){int ok=!strict||same(&existing,original);drop(&existing);if(!ok)message(fs,"Vorhandene Original-Sicherung ist verändert: ",target);return ok;}
    if(!original->exists)return 1;
    return fs->write_new(fs->context,target,original->data,original->size)&&expected(fs,target,original);
}
static int backups(const PrFS *fs,PrBuffer originals[3]){
    /* Validate all original backups before creating any backup files. */
    for(unsigned i=0;i<3;i++){
        char target[256];text(target,sizeof target,BACKUP);append(target,sizeof target,pr_paths[i]);
        PrBuffer b={0};if(!fs->read(fs->context,target,&b))return 0;
        int ok=!b.exists||same(&b,originals+i);drop(&b);
        if(!ok){message(fs,"Vorhandene Original-Sicherung ist verändert: ",target);return 0;}
    }
    for(unsigned i=0;i<3;i++)if(!backup_file(fs,pr_paths[i],originals+i,1))return 0;
    const char *extra[]={"config.json","bin/playliststate.bin","bin/playliststatetime.bin",
        "bin/playlist-resume.bin","bin/playlist-resume.log","bin/pi-playlist-resume-r03.bin",
        "bin/pi-playlist-resume-r03.log","PiPlaylistResume32.dll","PiPlaylistResume64.dll",RECEIPT};
    for(unsigned i=0;i<sizeof extra/sizeof extra[0];i++){
        PrBuffer b={0};if(!fs->read(fs->context,extra[i],&b))return 0;
        int ok=backup_file(fs,extra[i],&b,0);drop(&b);if(!ok)return 0;
    }
    return 1;
}
static unsigned sequence;
static int stage(const PrFS *fs,const char *path,const PrBuffer *b,char output[160]){
    for(unsigned tries=0;tries<32;tries++){
        char digits[12];unsigned n=0,v=++sequence;do{digits[n++]=(char)('0'+v%10);v/=10;}while(v);
        text(output,160,path);if(!append(output,160,".playlist-resume-"))return 0;
        while(n){char c[2]={digits[--n],0};if(!append(output,160,c))return 0;}
        if(!append(output,160,".tmp"))return 0;
        PrBuffer old={0};if(!fs->read(fs->context,output,&old))return 0;
        int exists=old.exists;drop(&old);if(exists)continue;
        if(!fs->write_new(fs->context,output,b->data,b->size))return 0;
        if(!expected(fs,output,b)){fs->remove(fs->context,output);return 0;}return 1;
    }
    return 0;
}

int pr_run(const PrFS *fs,int action){
    Inventory inventory;PrStatus status;PrBuffer originals[3]={{0}},empty={0};int result=1;
    if(action!=1&&action!=2)return 1;
    Plan *p=pr_alloc(sizeof *p);if(!p){message(fs,"Nicht genügend Arbeitsspeicher.",0);return 1;}zero(p,sizeof *p);
    if(!read_inventory(fs,&inventory,&status)){message(fs,status.label,0);message(fs,status.detail,0);goto finish;}
    for(unsigned i=0;i<3;i++){
        if(inventory.original[i]){
            if(!clone(originals+i,inventory.files[i].data,inventory.files[i].size))goto finish;
        }else if(!pr_transform(inventory.files+i,inventory.matched[i],0,originals+i)){
            message(fs,"Original konnte nicht rekonstruiert werden: ",pr_paths[i]);goto finish;
        }
    }
    for(unsigned i=0;i<5;i++){
        PrBuffer after={0};
        if(action==1){
            PrBuffer *original=i<3?originals+i:&empty;
            if(!pr_transform(original,pr_current[i],1,&after)){message(fs,"Ungültige Patchdaten: ",pr_paths[i]);goto finish;}
        }else if(i<3&&!clone(&after,originals[i].data,originals[i].size))goto finish;
        if(!add(p,pr_paths[i],inventory.files[i],after,0,action==1?(i>=3?0:2):(i<3?0:1)))goto finish;
    }
    for(unsigned i=5;i<7;i++)if(!add(p,pr_paths[i],inventory.files[i],empty,0,3))goto finish;
    if(action==1){
        if(!migrate_pair(fs,p,"bin/pi-playlist-resume-r03.bin","bin/playlist-resume.bin",1)||
           !migrate_pair(fs,p,"bin/pi-playlist-resume-r03.log","bin/playlist-resume.log",0))goto finish;
    }
    PrBuffer receipt={0};if(action==1&&!clone(&receipt,pr_receipt,pr_receipt_size))goto finish;
    if(!add(p,RECEIPT,inventory.files[7],receipt,0,4))goto finish;
    if(!p->count){message(fs,action==1?"PlaylistResume v1.0 ist bereits vollständig installiert.":"Die Originaldateien sind bereits vorhanden.",0);result=0;goto finish;}
    if(!fs->stopped(fs->context)){message(fs,"Wallpaper Engine läuft noch. Bitte über das Taskleistensymbol vollständig beenden und erneut versuchen.",0);goto finish;}
    if(!backups(fs,originals)){message(fs,"Sicherung fehlgeschlagen. Programmdateien wurden nicht geändert.",0);goto finish;}
    for(unsigned i=1;i<p->count;i++){
        Job j=p->jobs[i];unsigned n=i;while(n&&p->jobs[n-1].rank>j.rank){p->jobs[n]=p->jobs[n-1];n--;}p->jobs[n]=j;
    }
    for(unsigned i=0;i<p->count;i++)if(p->jobs[i].after.exists){
        Job *j=p->jobs+i;
        if(!stage(fs,j->path,&j->after,j->temp)){message(fs,"Vorbereiten fehlgeschlagen: ",j->path);goto rollback;}
        j->staged=1;
    }
    for(unsigned i=0;i<p->count;i++){
        Job *j=p->jobs+i;
        if(!expected(fs,j->path,&j->before)){message(fs,"Datei wurde zwischenzeitlich geändert: ",j->path);goto rollback;}
        int ok=j->after.exists?fs->replace(fs->context,j->temp,j->path):fs->remove(fs->context,j->path);
        if(!ok){message(fs,"Datei konnte nicht ersetzt oder entfernt werden: ",j->path);goto rollback;}
        j->committed=1;j->staged=0;
        if(!expected(fs,j->path,&j->after)){message(fs,"Prüfung nach dem Ersetzen fehlgeschlagen: ",j->path);goto rollback;}
        message(fs,j->after.exists?"Übernommen: ":"Entfernt: ",j->path);
    }
    message(fs,action==1?"PlaylistResume v1.0 wurde installiert.":"Originaldateien wurden wiederhergestellt. Positionen und Einstellungen bleiben erhalten.",0);
    message(fs,"Sicherung: ",BACKUP);result=0;goto finish;
  rollback:
    result=1;
    for(unsigned i=p->count;i;i--){
        Job *j=p->jobs+i-1;if(!j->committed)continue;
        int ok=expected(fs,j->path,&j->after);
        if(ok&&j->before.exists){
            char temporary[160];ok=stage(fs,j->path,&j->before,temporary);
            if(ok){ok=fs->replace(fs->context,temporary,j->path);if(!ok)fs->remove(fs->context,temporary);}
        }else if(ok)ok=fs->remove(fs->context,j->path);
        if(!ok||!expected(fs,j->path,&j->before)){message(fs,"Rücknahme fehlgeschlagen: ",j->path);result=2;}
    }
    message(fs,result==2?"Rücknahme unvollständig. Originale liegen unter playlist-resume-backup.":"Der vorherige Stand wurde beibehalten oder wiederhergestellt.",0);
  finish:
    for(unsigned i=0;i<p->count;i++)if(p->jobs[i].staged)fs->remove(fs->context,p->jobs[i].temp);
    for(unsigned i=0;i<3;i++)drop(originals+i);
    inventory_drop(&inventory);plan_drop(p);return result;
}

int pr_vdf_paths(const unsigned char *data,size_t size,char paths[][1024],unsigned capacity){
    size_t at=0;unsigned count=0;int want=0;
    while(at<size){
        if(data[at]=='/'&&at+1<size&&data[at+1]=='/'){while(at<size&&data[at]!='\n')at++;continue;}
        if(data[at++]!='"')continue;
        char token[1024];unsigned n=0;int closed=0,valid=1;
        while(at<size){
            unsigned char c=data[at++];if(c=='"'){closed=1;break;}
            if(c=='\\'&&at<size){unsigned char next=data[at];if(next=='\\'||next=='"'){c=next;at++;}}
            if(!c||n>=1023)valid=0;else token[n++]=(char)c;
        }
        token[n]=0;if(!closed)break;
        if(want){if(valid&&n&&count<capacity){copy(paths[count],token,n+1);count++;}want=0;}
        else if(valid&&string_equal(token,"path"))want=1;
    }
    return (int)count;
}
