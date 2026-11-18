#!/usr/bin/env python3
"""Localiza gold chunks y prepara la auditoría de cross-lingual con la caché E5.

Solo ejecuta retrieval de DEV y auditoría restringida al idioma de consulta en
candidatas CROSS (TEST). NO calcula rendimiento TEST, para evitar ajuste al test.
"""
import argparse,csv,json,hashlib,re
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np


def csv_read(file):
    with Path(file).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def csv_write(path,rows,cols):
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)

def load_corpus(path):
    return {d['document_id']:d for d in (json.loads(line) for line in Path(path).open(encoding='utf-8') if line.strip())}

def gold_local_chunks(tok,full_text,quote,usable):
    where=full_text.find(quote)
    if where<0:raise ValueError('La evidencia citada no aparece EXACTAMENTE en el texto del artículo')
    enc=tok(full_text, add_special_tokens=False, return_offsets_mapping=True, truncation=False)
    offsets=enc['offset_mapping']
    if not offsets:raise ValueError('El tokenizador no devuelve offsets del texto')
    first=where;last=where+len(quote)
    touched=[i//usable for i,(a,b) in enumerate(offsets) if a<last and b>first]
    if not touched:raise ValueError('Ningún token coincide con la evidencia')
    return sorted(set(touched))

def main():
    p=argparse.ArgumentParser(description='Revisión del banco de preguntas BDA sobre caché E5 existente')
    p.add_argument('--corpus',default='data/corpus_wikipedia_ciencia/corpus_candidato.jsonl')
    p.add_argument('--preguntas',default='data/evaluacion/banco_v1/preguntas_candidatas.csv')
    p.add_argument('--semantic-cache',default='data/evaluacion/semantic')
    p.add_argument('--out',default='data/evaluacion/banco_v1/revision')
    p.add_argument('--top-cross',type=int,default=40)
    p.add_argument('--top-dev',type=int,default=10)
    args=p.parse_args()
    if args.top_cross<1 or args.top_dev<1:p.error('Los top deben ser positivos')
    corpus_hash=hashlib.sha256(Path(args.corpus).read_bytes()).hexdigest()
    cache=Path(args.semantic_cache)
    manifest=json.loads((cache/'manifest_embeddings.json').read_text(encoding='utf-8'))
    if corpus_hash!=manifest['sha256_corpus']:
        raise ValueError('Los embeddings corresponden a OTRO corpus; vuelve a ejecutar la auditoría semántica original')
    if manifest.get('model')!='intfloat/multilingual-e5-base':
        raise ValueError('Modelo de embeddings distinto del E5 usado en el protocolo')
    usable=manifest['usable_text_tokens']
    if usable!=252:raise ValueError(f'Se esperaban 252 tokens útiles, manifest contiene {usable}')
    emb=np.load(cache/'embeddings_e5.npy',mmap_mode='r')
    meta=[json.loads(line) for line in (cache/'chunks_indexados.jsonl').open(encoding='utf-8') if line.strip()]
    # El siguiente chequeo comprueba explícitamente las tres cantidades
    if not (len(emb)==len(meta)==manifest['chunks']):raise ValueError('Caché incompleta')
    if len(meta)!=28640:raise ValueError(f'Corpus esperado con 28640 chunks, encontrados {len(meta)}')
    idx_by_doc=defaultdict(dict);idx_by_lang=defaultdict(list)
    for i,m in enumerate(meta):
        idx_by_doc[m['document_id']][int(m['chunk_index'])]=i
        idx_by_lang[m['language']].append(i)
    for lang in idx_by_lang:idx_by_lang[lang]=np.asarray(idx_by_lang[lang],dtype=np.int32)
    qs=csv_read(args.preguntas);docs=load_corpus(args.corpus)
    if len(qs)!=60:raise ValueError(f'Se esperaban 60 candidatas, recibidas {len(qs)}')
    from sentence_transformers import SentenceTransformer
    model=SentenceTransformer('intfloat/multilingual-e5-base',trust_remote_code=False)
    tok=model.tokenizer
    if not getattr(tok,'is_fast',False):raise ValueError('Se necesita tokenizador rápido para offsets de evidencia')
    enriched=[];gold_indices={}
    for r in qs:
        did=r['gold_document_id'];src=docs[did];quote=r['evidence_quote'];answer=r['expected_answer']
        # La respuesta puede estar traducida en preguntas cross-lingual.
        # Si se suministra source_answer_span, validamos la expresión ORIGINAL
        # de la fuente en vez de exigir que la traducción exista literalmente.
        answer_span = (r.get('source_answer_span') or answer).strip()
        if quote not in src['text']:
            raise ValueError(f'La evidencia de {r["question_id"]} no aparece exactamente en el corpus')
        if not answer_span or answer_span.casefold() not in quote.casefold():
            raise ValueError(f'La expresión de respuesta de {r["question_id"]} no aparece en la evidencia original')
        if str(src['revision_id'])!=r['source_revision_id']:
            raise ValueError('Revisión del artículo ha cambiado para '+r['question_id'])
        ks=gold_local_chunks(tok,src['text'],quote,usable)
        indices=[idx_by_doc[did][k] for k in ks]
        gold_indices[r['question_id']]=indices
        rr=dict(r);rr['gold_chunk_ids']=json.dumps([f'{did}#{k}' for k in ks],ensure_ascii=False)
        rr['notes']='Gold calculado por offsets de token; confirmar manualmente evidencia suficiente. TEST NO EVALUADO.'
        enriched.append(rr)
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    csv_write(out/'preguntas_con_gold_provisional.csv',enriched,list(enriched[0]))
    # Solo DEV y candidatas cross: el rendimiento del TEST monolingüe queda sin tocar.
    batch=[r for r in enriched if r['split']=='dev' or r['question_type']=='cross']
    qemb=model.encode(['query: '+r['question'] for r in batch],normalize_embeddings=True,
                       convert_to_numpy=True,show_progress_bar=False)
    dev_out=[];cross_out=[];dev_scores=[]
    for r,qv in zip(batch,qemb):
        sim=np.asarray(emb)@np.asarray(qv,dtype=np.float32)
        qid=r['question_id']
        if r['split']=='dev':
            order=np.argsort(-sim)[:args.top_dev]
            positions={int(ii):rank for rank,ii in enumerate(np.argsort(-sim),1)}
            gs=gold_indices[qid]
            gold_min=min(positions[ii] for ii in gs)
            gold_full=max(positions[ii] for ii in gs)
            dev_scores.append({'question_id':qid,'rank_first_gold_chunk':gold_min,
              'rank_all_gold_chunks':gold_full,'hit5_provisional':gold_full<=5,
              'note':'Solo diagnóstico DEV; gold provisional por offsets'})
            for rank,idx in enumerate(order,1):
                m=meta[int(idx)]
                dev_out.append({'question_id':qid,'rank':rank,'score':float(sim[idx]),
                     'title':m['title'],'language':m['language'],'document_id':m['document_id'],
                     'chunk_index':m['chunk_index'],'gold_provisional':int(idx) in gs,
                     'fragment':m['text'][:950]})
        if r['question_type']=='cross':
            # Nunca forzar idioma fuente en la evaluación principal.
            # Aquí solo buscamos fuentes que INVALIDARÍAN la exclusividad.
            candidates=idx_by_lang[r['question_language']]
            scores=sim[candidates];order=np.argsort(-scores)[:args.top_cross]
            for rank,pos in enumerate(order,1):
                idx=int(candidates[pos]);m=meta[idx]
                cross_out.append({'question_id':qid,'question':r['question'],
                 'expected_answer':r['expected_answer'],'rank_same_language':rank,
                 'similarity':round(float(sim[idx]),6),'document_id':m['document_id'],
                 'title':m['title'],'chunk_index':m['chunk_index'],'url':m['url'],
                 'fragment':m['text'][:1800],
                 'contains_sufficient_answer':'PENDIENTE_REVISION_HUMANA',
                 'review_notes':''})
        print(f'{qid}: recuperación de auditoría completada',flush=True)
    if dev_out:csv_write(out/'top_dev.csv',dev_out,list(dev_out[0]))
    if dev_scores:csv_write(out/'resumen_dev.csv',dev_scores,list(dev_scores[0]))
    if cross_out:csv_write(out/'revision_crosslingual_semantica.csv',cross_out,list(cross_out[0]))
    report={
      'corpus_sha256':corpus_hash,'chunks':len(meta),'questions':len(qs),
      'dev_questions_evaluated':len(dev_scores),'test_questions_evaluated':0,
      'cross_candidates_to_review':len([r for r in qs if r['question_type']=='cross']),
      'same_language_fragments_for_manual_review':len(cross_out),
      'dev_hit5_provisional':(sum(bool(r['hit5_provisional']) for r in dev_scores)/len(dev_scores) if dev_scores else None),
      'status':'AUDITORIA_SEMANTICA_CROSS_PENDIENTE_REVISION_HUMANA',
      'limitations':['No hay un clasificador fiable de suficiencia de respuesta en esta herramienta.',
                     'Las 10 cross se revisan en su idioma de consulta; comprobar también otras fuentes y paráfrasis.',
                     'El TEST queda sin evaluar; medirlo solo tras la ingesta y el ajuste sobre DEV.',
                     'Si un gold abarca varios chunks, confirmar manualmente cuáles son suficientes.']}
    (out/'informe_revision.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
