#!/usr/bin/env python3
"""Audita un corpus JSONL y preguntas con evidencias comprobables.

Para contar chunks EXACTOS usa el MISMO tokenizer y cálculo de check_project.py:
  n_chunks = max(1, ceil(len(tokenizer(text, add_special_tokens=False)["input_ids"]) / usable))
con usable = 256 - len(tokenizer("passage: ")["input_ids"]).

La comprobación cross-lingual es LEXICAL (alias de respuesta), no semántica.
"""
import argparse
import csv
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

CHUNK_TOKENS = 256

def norm(s):
    s = unicodedata.normalize('NFKD', str(s).casefold())
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', s)

def write_csv(path,rows,cols):
    with Path(path).open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)

def load_documents(path):
    docs=[]
    with path.open(encoding='utf8') as f:
        for line_no,line in enumerate(f,1):
            if not line.strip():continue
            obj=json.loads(line)
            for key in ('document_id','text','language','topic','title'):
                if key not in obj:
                    raise ValueError(f'Linea {line_no}: campo ausente {key}')
            docs.append(obj)
    return docs

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--corpus',default='data/corpus_wikipedia_ciencia/corpus_candidato.jsonl')
    ap.add_argument('--preguntas',default='data/evaluacion/preguntas_piloto_v2.csv')
    ap.add_argument('--out',default='data/evaluacion/auditoria')
    ap.add_argument('--model',default='intfloat/multilingual-e5-base')
    ap.add_argument('--passage-prefix',default='passage: ')
    ap.add_argument('--sin-tokenizador',action='store_true',help='Solo auditoría documental y lexical; no cuenta chunks')
    args=ap.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    docs=load_documents(Path(args.corpus))
    ids=Counter(str(d['document_id']) for d in docs)
    duplicate_ids={id:n for id,n in ids.items() if n>1}
    qids=Counter(str(d.get('wikidata_id','')).strip() for d in docs if d.get('wikidata_id'))
    repeated_qids={id:n for id,n in qids.items() if n>1}
    hashes=Counter(hashlib.sha256(d['text'].encode('utf-8')).hexdigest() for d in docs)
    dup_texts=sum(n-1 for n in hashes.values() if n>1)
    summary={'documents':len(docs),'documents_by_language':dict(Counter(d['language'] for d in docs)),
      'documents_by_language_topic':{f'{lang}:{topic}':n for (lang,topic),n in sorted(Counter((d['language'],d['topic']) for d in docs).items())},
      'duplicate_document_ids':duplicate_ids,'duplicate_wikidata_ids':repeated_qids,'exact_duplicate_text_excess':dup_texts,
      'chunk_count_status':'NO_CALCULADO'}
    by_id={d['document_id']:d for d in docs}
    tok=None;usable=None;chunk_rows=[];by_lang_chunks=defaultdict(int);offset_token_cache={}
    if not args.sin_tokenizador:
        from sentence_transformers import SentenceTransformer
        print('Cargando tokenizer desde el modelo: ',args.model,flush=True)
        tok=SentenceTransformer(args.model,trust_remote_code=False).tokenizer
        overhead=len(tok(args.passage_prefix)['input_ids'])
        usable=CHUNK_TOKENS-overhead
        if usable<=0:raise RuntimeError('Prefijo demasiado largo')
        print(f'Token por chunk: {usable}; contando {len(docs)} documentos...',flush=True)
        for i,d in enumerate(docs,1):
            tokens=len(tok(d['text'],add_special_tokens=False,verbose=False)['input_ids'])
            n=max(1,math.ceil(tokens/usable))
            by_lang_chunks[d['language']]+=n
            chunk_rows.append({'document_id':d['document_id'],'language':d['language'],'topic':d['topic'],
                'title':d['title'],'tokens_text':tokens,'chunks_256':n,'url':d.get('url','')})
            if i%500==0:print(f'  Procesados {i}/{len(docs)}',flush=True)
        total=sum(by_lang_chunks.values())
        summary.update({'chunk_count_status':'EXACTO_TOKENIZADOR','model':args.model,'chunk_tokens':CHUNK_TOKENS,
            'passage_prefix':args.passage_prefix,'overhead':overhead,'usable_text_tokens':usable,
            'chunks_total':total,'chunks_by_language':dict(by_lang_chunks),
            'chunk_share_by_language':{lang:round(c/total,5) for lang,c in by_lang_chunks.items()}})
        write_csv(out/'chunks_por_documento.csv',chunk_rows,['document_id','language','topic','title','tokens_text','chunks_256','url'])
    else:
        print('No se ha ejecutado el tokenizador: auditoría léxica solamente.',flush=True)

    with Path(args.preguntas).open(encoding='utf-8-sig',newline='') as f:
        questions=list(csv.DictReader(f))
    normalized_by_lang=defaultdict(list)
    for d in docs:
        normalized_by_lang[d['language']].append((d,norm(d['text'])))
    qa_rows=[]; same_lang_hits=[]
    for q in questions:
        qid=q['question_id'];source_id=q['source_document_id']
        source=by_id.get(source_id)
        valid_source=bool(source)
        evidence_exact=bool(source and q['evidence_quote'] in source['text'])
        aliases=[a.strip() for a in q['answer_aliases'].split('|') if a.strip()]
        source_answer_all=bool(source and any(norm(a) in norm(q['evidence_quote']) for a in aliases))
        query_lang=q['question_language'];evidence_lang=q['evidence_language']
        cross=query_lang!=evidence_lang
        hits=[]
        if cross:
            for d,normalized_text in normalized_by_lang[query_lang]:
                which=[a for a in aliases if norm(a) in normalized_text]
                if which:
                    hits.append({'question_id':qid,'document_id':d['document_id'],'title':d['title'],
                                 'language':d['language'],'matching_aliases':' | '.join(which),'url':d.get('url','')})
        same_lang_hits.extend(hits)
        if not valid_source or not evidence_exact or not source_answer_all:
            status='REVISAR_FUENTE_EVIDENCIA'
        elif not cross:status='NO_APLICA_MONOLINGUAL'
        elif hits:status='COINCIDENCIA_LITERAL_EN_IDIOMA_PREGUNTA_REVISAR'
        else:status='SIN_COINCIDENCIA_LITERAL_AUN_FALTA_AUDITORIA_SEMANTICA'
        chunk_span=''
        if tok and source and evidence_exact:
            start=source['text'].find(q['evidence_quote']);end=start+len(q['evidence_quote'])
            offsets=tok(source['text'],add_special_tokens=False,return_offsets_mapping=True,verbose=False)['offset_mapping']
            overlapping=[i//usable for i,(a,b) in enumerate(offsets) if a<end and b>start]
            if overlapping:
                chunk_span=f'{min(overlapping)}' if min(overlapping)==max(overlapping) else f'{min(overlapping)}-{max(overlapping)}'
        qa_rows.append({'question_id':qid,'question_language':query_lang,'evidence_language':evidence_lang,
          'source_document_id':source_id,'source_title':q['source_title'],
          'source_exists':valid_source,'evidence_quote_exact':evidence_exact,'answer_aliases_in_source':source_answer_all,
          'same_language_literal_hit_documents':len(hits),'lexical_status':status,
          'source_chunk_indices_zero_based':chunk_span,'retrieval_status':'PENDIENTE_EMBEDDINGS_PGVECTOR'})
    write_csv(out/'preguntas_auditadas.csv',qa_rows,['question_id','question_language','evidence_language','source_document_id','source_title','source_exists','evidence_quote_exact','answer_aliases_in_source','same_language_literal_hit_documents','lexical_status','source_chunk_indices_zero_based','retrieval_status'])
    write_csv(out/'coincidencias_idioma_pregunta.csv',same_lang_hits,['question_id','document_id','title','language','matching_aliases','url'])
    summary['questions_audited']=len(questions)
    summary['question_summary']={q['question_id']:{'lexical_status':q['lexical_status'],
        'same_language_literal_hit_documents':q['same_language_literal_hit_documents']} for q in qa_rows}
    summary['important_limitations']=[
     'La ausencia de menciones exactas NO prueba exclusividad semántica cross-lingual; requieren revisión manual y búsqueda vectorial/FTS.',
     'El corpus completo se ha congelado por revision_id para poder reproducir la evaluación.',
     'El contador de chunks sigue el algoritmo de check_project.py, pero la segmentación final de la ingesta debe ser idéntica.']
    (out/'informe_auditoria.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print('Documentos:',len(docs),'| exact duplicates:',dup_texts)
    if tok:print('Chunks EXACTOS:',summary['chunks_total'],'por idioma:',summary['chunks_by_language'])
    for q in qa_rows:print(q['question_id'],q['lexical_status'],'coincidencias:',q['same_language_literal_hit_documents'])
    print('Archivos en:',out.resolve())

if __name__=='__main__':main()
