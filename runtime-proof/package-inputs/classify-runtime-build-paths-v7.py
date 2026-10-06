from pathlib import Path
from collections import Counter
import dis
import hashlib
import json
import marshal
import struct
import sys
import types

def classify(stage,roots,assembled,policy_path,output):
    policy_raw=policy_path.read_bytes()
    assert hashlib.sha256(policy_raw).hexdigest()=='6d08330483ae7569153701c4eb5d211c838bb7ab6909452aa54bd5ad9e401e5d'
    policy=json.loads(policy_raw)
    errors=[]
    counts=Counter()
    files={}
    helper_matches={}
    bytecode_uses=[]
    native_rows=[]
    native_interfaces={}
    assembled_data=json.loads(assembled.read_text())
    raw_references={name:[] for name in roots}
    stage_root=roots['stage']
    helper='_jac_runtime_impl_patch_filename'
    def forbidden(value):
        if isinstance(value,bytes):
            return any(root.encode() in value for root in roots.values())
        return isinstance(value,str) and any(root in value for root in roots.values())
    def reject(message):
        errors.append(message)
    def scalars(value):
        if isinstance(value,(str,bytes)):
            yield value
        elif isinstance(value,(tuple,list,set,frozenset)):
            for item in value:
                yield from scalars(item)
        elif isinstance(value,dict):
            for key,item in value.items():
                yield from scalars(key)
                yield from scalars(item)
    def inspect_code(code,file,root,alias_binding):
        counts['code_objects']+=1
        for field in ('co_filename','co_name','co_qualname','co_names','co_varnames','co_freevars','co_cellvars'):
            if any(forbidden(v) for v in scalars(getattr(code,field))):
                reject(file+': build root in '+field)
        expected=policy['helper_codes'].get(file.removeprefix('site/jaclang/_precompiled/cpython-314/'))
        if expected and code.co_qualname==expected['qualname']:
            found=hashlib.sha256(marshal.dumps(code,policy['helper_marshal_version'])).hexdigest()
            if found!=expected['marshal_sha256']:
                reject(file+': diagnostic helper code changed')
            helper_matches[file]=found
        ins=[i for i in dis.get_instructions(code) if i.opname!='EXTENDED_ARG']
        jumps={i.argval for i in ins if i.opcode in dis.hasjump}
        jumps.update(e.target for e in dis.Bytecode(code).exception_entries)
        bindings=[]
        for n,i in enumerate(ins):
            if i.argval==helper and i.opname.startswith(('STORE','DELETE')):
                origin=n-2
                while origin>=1 and ins[origin].opname=='STORE_NAME' and ins[origin-1].opname=='IMPORT_FROM':
                    origin-=2
                if n>=2 and i.opname=='STORE_NAME' and ins[n-1].opname=='IMPORT_FROM' and ins[n-1].argval=='impl_patch_filename' and origin>=0 and ins[origin].opname=='IMPORT_NAME' and ins[origin].argval=='jaclang.lib.jaclib':
                    bindings.append(i.offset)
                else:
                    reject(file+': diagnostic helper alias overwritten')
        active_binding=min(bindings) if bindings else alias_binding
        for constant_index,value in enumerate(code.co_consts):
            if isinstance(value,types.CodeType):
                inspect_code(value,file,root,active_binding)
                continue
            if not any(forbidden(v) for v in scalars(value)):
                continue
            if not isinstance(value,str) or not value.startswith(stage_root+'/site/jaclang/') or not value.endswith('.jac') or value.removeprefix(stage_root+'/') not in assembled_data:
                reject(file+': unapproved build-root constant in '+code.co_qualname)
                continue
            loads=[(n,i) for n,i in enumerate(ins) if i.opname=='LOAD_CONST' and i.arg==constant_index]
            if not loads:
                reject(file+': unused forbidden constant')
            for n,i in loads:
                sequence=ins[max(0,n-2):n+2]
                valid=(len(sequence)==4 and sequence[0].opname=='LOAD_NAME' and sequence[0].argval==helper
                    and sequence[1].opname=='PUSH_NULL' and sequence[2] is i
                    and sequence[3].opname=='CALL' and sequence[3].arg==1
                    and active_binding is not None and (not bindings or sequence[0].offset>active_binding)
                    and not any(sequence[0].offset<target<=sequence[3].offset for target in jumps))
                if not valid:
                    reject(file+': forbidden path consumer at '+str(i.offset)+' in '+code.co_qualname)
                else:
                    counts['diagnostic_helper_calls']+=1
                    bytecode_uses.append(dict(file=file,qualname=code.co_qualname,offset=i.offset,
                        constant_index=constant_index,value=value,call_offset=sequence[3].offset))
        # An arg pointing at a forbidden constant must be a plain LOAD_CONST.
        for i in ins:
            if i.opcode in dis.hasconst and i.arg is not None and i.arg<len(code.co_consts):
                v=code.co_consts[i.arg]
                if not isinstance(v,types.CodeType) and any(forbidden(x) for x in scalars(v)) and i.opname!='LOAD_CONST':
                    reject(file+': non-load reference to forbidden constant')
    def jir(data,file):
        assert data[:4]==b'JIR\0'
        pos=data.find(b'JIRX',32)
        assert pos>=32 and not forbidden(data[:pos+4])
        pos+=4
        finished=False
        while pos<len(data):
            assert pos+5<=len(data)
            tag,size=data[pos],struct.unpack_from('<I',data,pos+1)[0]
            pos+=5
            assert pos+size<=len(data)
            part=data[pos:pos+size]
            pos+=size
            if tag==255:
                assert size==0 and pos==len(data)
                finished=True
                break
            if tag==2:
                code=marshal.loads(part)
                assert isinstance(code,types.CodeType)
                ins=[i for i in dis.get_instructions(code) if i.opname!='EXTENDED_ARG']
                inspect_code(code,file,code,None)
            elif forbidden(part):
                reject(file+': build-root bytes in JIR section '+str(tag))
                if tag==13:
                    counts['rejected_interface_sections']+=1
            if tag==13:
                counts['interface_sections']+=1
                assert len(part)>=64 and hashlib.sha256(part[64:]).hexdigest()==part[:64].decode()
            if tag==17:
                assert part[:4]==b'JNV1' and len(part)>=8
                variants=struct.unpack_from('<I',part,4)[0]
                cursor=8
                records={}
                for _ in range(variants):
                    size=struct.unpack_from('<I',part,cursor)[0]
                    cursor+=4
                    record=part[cursor:cursor+size]
                    assert len(record)==size and record[:4]==b'JNS1'
                    cursor+=size
                    head_len=struct.unpack_from('<I',record,4)[0]
                    stamp=record[8:8+head_len].decode()
                    assert len(stamp.split('\x1f'))==5 and stamp not in records
                    value=record[8+head_len:]
                    digest=value[:64].decode()
                    decoded=json.loads(value[64:])
                    fields={key:decoded[key] for key in ('format','module','prefix','exports','classes','enums','init','entry','demoted','clib_paths','python_imports','clib_symbol_lib','layout','headerless')}
                    assert hashlib.sha256(json.dumps(fields,sort_keys=True,separators=(',',':')).encode()).hexdigest()==digest
                    records[stamp]=digest
                assert cursor==len(part)
                native_interfaces[file]=records
        assert finished
    native_file='site/jaclang/compiler/libjac_compiler.so'
    layout_file=native_file+'.layout.json'
    def native(data):
        assert data[:6]==b'\x7fELF\x02\x01'
        if hashlib.sha256(data.replace(stage_root.encode(),b'__STAGE__')).hexdigest()!=policy['normalized_native_sha256']:
            reject('native bytes differ from independently pinned normalized artifact')
        header=struct.unpack_from('<16sHHIQQQIHHHHHH',data)
        assert header[11]==64
        sections=[struct.unpack_from('<IIQQQQIIQQ',data,header[6]+n*64) for n in range(header[12])]
        names=data[sections[header[13]][4]:sections[header[13]][4]+sections[header[13]][5]]
        allowed=set()
        for section in sections:
            name=names[section[0]:].split(b'\0',1)[0].decode()
            if section[1]==8:
                continue
            content=data[section[4]:section[4]+section[5]]
            if forbidden(content):
                if name!='.rodata' or section[2]!=2:
                    reject('native build-root reference outside readonly assertion data: '+name)
                    continue
                offset=0
                for value in content.split(b'\0'):
                    if forbidden(value):
                        normal=value.decode().replace(stage_root,'__STAGE__')
                        matches=[p for p in policy['native_assertions'] if p['section_offset']==offset and p['normalized']==normal]
                        if len(matches)!=1 or hashlib.sha256(normal.encode()).hexdigest()!=matches[0]['normalized_sha256']:
                            reject('unexpected native assertion at '+str(offset))
                        else:
                            expected_length=matches[0]['byte_length']+len(stage_root)-policy['origin_stage_length']
                            if len(value)!=expected_length:
                                reject('native assertion length changed')
                            allowed.update(range(section[4]+offset,section[4]+offset+len(value)))
                            native_rows.append(dict(section=name,section_offset=offset,byte_length=len(value),normalized=normal,
                                string_sha256=hashlib.sha256(value).hexdigest()))
                    offset+=len(value)+1
        for root in roots.values():
            pos=0
            needle=root.encode()
            while (pos:=data.find(needle,pos))>=0:
                if not all(n in allowed for n in range(pos,pos+len(needle))):
                    reject('native root outside exact approved assertion string at '+str(pos))
                pos+=len(needle)
        if len(native_rows)!=6:
            reject('native assertion set differs from six approved strings')
    for path in sorted(stage.rglob('*')):
        if path.is_symlink():
            reject('payload symlink: '+str(path.relative_to(stage)))
        if not path.is_file():
            continue
        file=str(path.relative_to(stage))
        data=path.read_bytes()
        files[file]=hashlib.sha256(data).hexdigest()
        for name,root in roots.items():
            if root.encode() in data:
                raw_references[name].append(file)
        if file.endswith('.jir'):
            jir(data,file)
        elif file==native_file:
            native(data)
        elif file==layout_file:
            layout=json.loads(data)
            if layout['artifact_sha256']!=hashlib.sha256((stage/native_file).read_bytes()).hexdigest():
                reject('native artifact hash does not match layout')
            if layout['unit_ids']!=policy['unit_ids'] or layout['unit_sources']!=policy['unit_sources']:
                reject('native portable units differ from reviewed source identities')
            units=layout['units']
            if len(units)!=len(layout['unit_ids']) or len(set(units))!=len(units):
                reject('native units not one-to-one')
            for unit,identity in zip(units,layout['unit_ids']):
                if unit!=stage_root+'/site/'+identity or assembled_data.get('site/'+identity)!=policy['unit_input_files'].get('site/'+identity):
                    reject('layout unit fails assembled-input identity/hash: '+identity)
            for name,digest in policy['unit_input_files'].items():
                if assembled_data.get(name)!=digest:
                    reject('native unit source input changed: '+name)
            remainder={k:v for k,v in layout.items() if k!='units'}
            if any(forbidden(v) for v in scalars(remainder)):
                reject('build root outside layout units')
            counts['verified_layout_units']=len(units)
        elif forbidden(data):
            reject('unclassified build-root reference: '+file)
    if len(helper_matches)!=2:
        reject('reviewed helper implementations not both present')
    sealed=json.loads((stage/'site/jaclang/_precompiled/MANIFEST.json').read_text())
    manifest_jirs=set()
    for row in sealed['modules'].values():
        file='site/jaclang/_precompiled/'+sealed['python_tag']+'/'+row['jir']
        if Path(row['jir']).is_absolute() or '..' in Path(row['jir']).parts:
            reject('unsafe sealed manifest path')
        manifest_jirs.add(file)
        if files.get(file)!=row['sha256']:
            reject('sealed JIR hash mismatch: '+file)
    if manifest_jirs!={file for file in files if file.endswith('.jir')}:
        reject('sealed manifest does not cover exact JIR set')
    counts['verified_manifest_jirs']=len(manifest_jirs)
    artifact=sealed['native']['artifact']
    if artifact['path']!='compiler/libjac_compiler.so' or artifact['sha256']!=files.get(native_file):
        reject('native sealed manifest artifact differs')
    native_units=sealed['native']['units']
    if {'jaclang/'+name for name in native_units}!=set(policy['unit_ids']):
        reject('sealed native unit identities differ')
    for name,row in native_units.items():
        file='site/jaclang/_precompiled/'+sealed['python_tag']+'/'+row['jir']
        layout=json.loads((stage/layout_file).read_text())
        matching=[digest for stamp,digest in native_interfaces.get(file,{}).items()
            if stamp.split('\x1f')[0]==sealed['compiler_digest'] and stamp.split('\x1f')[2]==layout['triple']]
        if row['iface_digest'] not in matching:
            reject('sealed native interface hash mismatch: '+name)
    receipt=dict(status='passed' if not errors else 'rejected',
        scope='Read-only exact diagnostic classification; requires separate hidden-source relocation and application gates',
        roots=roots,policy_sha256=hashlib.sha256(policy_raw).hexdigest(),
        executed_classifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        assembled_input_manifest_sha256=hashlib.sha256(assembled.read_bytes()).hexdigest(),
        sealed_manifest_sha256=hashlib.sha256((stage/'site/jaclang/_precompiled/MANIFEST.json').read_bytes()).hexdigest(),
        stage_files=files,stage_inventory_sha256=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        counts=dict(counts),helper_code_bindings=helper_matches,bytecode_uses=bytecode_uses,native_assertions=native_rows,
        raw_build_reference_files=raw_references,errors=errors)
    output.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    print(json.dumps(dict(status=receipt['status'],counts=receipt['counts'],error_count=len(errors),errors=errors[:10],output=str(output))))
    return receipt

if __name__=='__main__':
    stage,roots,assembled,policy,output=map(Path,sys.argv[1:])
    result=classify(stage,json.loads(roots.read_text()),assembled,policy,output)
    raise SystemExit(0 if result['status']=='passed' else 1)
