#!/usr/bin/env python3
"""Auditoría vectorial del corpus Wikipedia BDA (E5), SIN PostgreSQL.

- Segmentación: 256 tokens totales; reserva prefijo/special tokens.
- Embeddings normalizados E5 con prefijos query:/passage:.
- Recuperación exhaustiva mediante coseno, sin ANN, útil como referencia previa a pgvector.
- Exporta candidatos del MISMO idioma para auditoría humana de exclusividad.

IMPORTANTE: similaridad alta no implica evidencia ni exclusividad lingüística.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from collections import Counter

import numpy as np


def csv_rows(path):
    with Path(path).open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def save_csv(path, rows, cols):
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def hash_file(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(2**20), b''):
            h.update(block)
    return h.hexdigest()


def parse_gold_span(s):
    s = (s or '').strip()
    if not s:
        return set()
    out = set()
    for part in s.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a,b = map(int, part.split('-', 1))
            if a > b or b-a > 100:
                raise ValueError(f'Rango de chunks de evidencia inválido: {s}')
            out.update(range(a,b+1))
        else:
            out.add(int(part))
    return out


def create_chunks(corpus_path, model, usable):
    """Devuelve metadatos y pasajes; usa el mismo número de tokens por chunk que la auditoría anterior."""
    tok = model.tokenizer
    metadata = []
    passages = []
    docs = 0
    with corpus_path.open('r',encoding='utf-8') as f:
        for lineno,line in enumerate(f,1):
            if not line.strip():
                continue
            d = json.loads(line)
            for key in ['document_id','language','topic','title','text']:
                if key not in d:
                    raise ValueError(f'Falta {key} en documento de línea {lineno}')
            ids = tok(d['text'], add_special_tokens=False, verbose=False)['input_ids']
            pieces = [ids[start:start+usable] for start in range(0,len(ids),usable)] or [[]]
            for k,piece in enumerate(pieces):
                chunk_text = tok.decode(piece, skip_special_tokens=True, clean_up_tokenization_spaces=False)
                metadata.append({
                    'document_id':str(d['document_id']), 'title':str(d['title']),
                    'language':str(d['language']), 'topic':str(d['topic']),
                    'chunk_index':k, 'url':str(d.get('url','')), 'text':chunk_text
                })
                passages.append(chunk_text)
            docs += 1
            if docs % 500 == 0:
                print(f'  Segmentación: {docs} documentos, {len(metadata)} chunks',flush=True)
    return metadata, passages, docs


def load_or_embed(args, model, out):
    corpus_path = Path(args.corpus)
    sig = {
        'sha256_corpus':hash_file(corpus_path),
        'model':args.model, 'chunk_tokens':256,
        'passage_prefix':'passage: ', 'query_prefix':'query: ',
        'encoding':'tokenizer.decode(clean_up_tokenization_spaces=False)',
        'dimension':int(model.get_sentence_embedding_dimension()),
    }
    overhead = len(model.tokenizer('passage: ')['input_ids'])
    usable = 256-overhead
    if usable < 1:
        raise ValueError('No queda capacidad de tokens para el texto')
    sig['usable_text_tokens'] = usable
    meta_path = out/'chunks_indexados.jsonl'
    emb_path = out/'embeddings_e5.npy'
    man_path = out/'manifest_embeddings.json'
    if not args.rebuild and all(p.exists() for p in (meta_path,emb_path,man_path)):
        old = json.loads(man_path.read_text(encoding='utf-8'))
        if all(old.get(k) == v for k,v in sig.items()):
            print('Reutilizando embeddings y chunks verificados por hash...',flush=True)
            meta = [json.loads(line) for line in meta_path.open(encoding='utf-8') if line.strip()]
            emb = np.load(emb_path,mmap_mode='r')
            if len(meta)==len(emb)==old.get('chunks'):
                return meta,emb,old
            print('Caché incompleta: recalculando...',flush=True)
    print('Tokenizando corpus completo (puede tardar unos minutos)...',flush=True)
    meta, passages, n_docs = create_chunks(corpus_path, model, usable)
    expected = args.expected_chunks
    if expected and len(meta) != expected:
        raise ValueError(f'Chunks generados = {len(meta)}, pero esperados = {expected}. Revisa corpus, modelo o tokenizador.')
    dim = sig['dimension']
    print(f'Documentos: {n_docs}; chunks: {len(meta)}; dimensión: {dim}',flush=True)
    # Escribimos los chunks antes de generar embeddings: si falla, no se considera caché completa.
    with meta_path.open('w', encoding='utf-8') as f:
        for m in meta:
            f.write(json.dumps(m,ensure_ascii=False)+'\n')
    emb = np.lib.format.open_memmap(emb_path,mode='w+',dtype='float32',shape=(len(meta),dim))
    for start in range(0,len(passages),args.batch_size):
        stop=min(start+args.batch_size,len(passages))
        batch=['passage: '+s for s in passages[start:stop]]
        v=model.encode(batch, batch_size=args.batch_size, normalize_embeddings=True,
                       convert_to_numpy=True, show_progress_bar=False)
        emb[start:stop]=np.asarray(v,dtype=np.float32)
        if stop % 2048 < args.batch_size or stop == len(passages):
            emb.flush()
            print(f'  Embeddings {stop}/{len(passages)}',flush=True)
    emb.flush()
    del passages
    sig.update({'documents':n_docs, 'chunks':len(meta),
                'chunks_by_language':dict(Counter(m['language'] for m in meta))})
    man_path.write_text(json.dumps(sig,indent=2,ensure_ascii=False),encoding='utf-8')
    return meta, emb, sig


def main():
    p=argparse.ArgumentParser(description='Auditar semánticamente recuperación y posibles fuentes del mismo idioma')
    p.add_argument('--corpus',default='data/corpus_wikipedia_ciencia/corpus_candidato.jsonl')
    p.add_argument('--preguntas',default='data/evaluacion/preguntas_piloto_v2.csv')
    p.add_argument('--auditoria',default='data/evaluacion/auditoria/preguntas_auditadas.csv')
    p.add_argument('--out',default='data/evaluacion/semantic')
    p.add_argument('--model',default='intfloat/multilingual-e5-base')
    p.add_argument('--batch-size',type=int,default=32)
    p.add_argument('--top',type=int,default=30,help='Top global guardado por pregunta')
    p.add_argument('--revision-top',type=int,default=40,help='Top del idioma de consulta para revisar manualmente')
    p.add_argument('--expected-chunks',type=int,default=28640,help='0 desactiva la comprobación')
    p.add_argument('--rebuild',action='store_true',help='Ignora la caché de embeddings')
    args=p.parse_args()
    if args.batch_size<1 or args.top<1 or args.revision_top<1:
        p.error('Los tamaños de lote y los top deben ser mayores que cero.')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    questions=csv_rows(args.preguntas)
    audited={row['question_id']:row for row in csv_rows(args.auditoria)} if Path(args.auditoria).exists() else {}
    if not questions:
        raise ValueError('El CSV de preguntas está vacío')
    from sentence_transformers import SentenceTransformer
    print('Cargando modelo E5...',flush=True)
    model=SentenceTransformer(args.model,trust_remote_code=False)
    meta, emb, manifest=load_or_embed(args,model,out)
    n=len(meta)
    lang_idx={lang:np.array([i for i,m in enumerate(meta) if m['language']==lang],dtype=np.int32)
              for lang in set(m['language'] for m in meta)}
    sources={}
    for i,m in enumerate(meta):
        sources.setdefault(m['document_id'],[]).append(i)
    global_rows=[]; same_lang_rows=[]; summary_rows=[]
    embeddings_np=np.asarray(emb,dtype=np.float32)
    for q in questions:
        qid=q['question_id'];question=q['question']
        qlang=q['question_language'];e_lang=q['evidence_language']
        source_id=q['source_document_id']; cross=qlang!=e_lang
        q_emb=model.encode(['query: '+question],convert_to_numpy=True,normalize_embeddings=True,
                           show_progress_bar=False)[0].astype(np.float32)
        sim=embeddings_np@q_emb
        order=np.argsort(-sim,kind='stable')
        rank=np.empty(n,dtype=np.int32); rank[order]=np.arange(1,n+1)
        source_indices=sources.get(source_id,[])
        doc_rank=min((int(rank[i]) for i in source_indices),default=None)
        gold_locals=parse_gold_span(audited.get(qid,{}).get('source_chunk_indices_zero_based',''))
        gold=[i for i in source_indices if meta[i]['chunk_index'] in gold_locals]
        gold_rank=min((int(rank[i]) for i in gold),default=None)
        full_evidence_rank=max((int(rank[i]) for i in gold),default=None)
        gold_found=bool(gold)
        top_k=order[:args.top]
        for i in top_k:
            m=meta[int(i)]
            global_rows.append({
                'question_id':qid,'rank':int(rank[i]),'score':round(float(sim[i]),6),
                'document_id':m['document_id'],'language':m['language'],'topic':m['topic'],
                'title':m['title'],'chunk_index':m['chunk_index'],
                'es_fuente_esperada':m['document_id']==source_id,
                'es_chunk_evidencia':int(i) in gold,'url':m['url'],
                'fragmento':m['text'][:1700]
            })
        same=lang_idx.get(qlang,np.empty(0,dtype=np.int32))
        same_order=same[np.argsort(-sim[same],kind='stable')][:args.revision_top]
        if cross:
            for j,i in enumerate(same_order,1):
                m=meta[int(i)]
                same_lang_rows.append({
                    'question_id':qid,'question':question,'respuesta_esperada':q['expected_answer'],
                    'rank_idioma_pregunta':j,'rank_global':int(rank[i]),
                    'score':round(float(sim[i]),6),
                    'document_id':m['document_id'],'title':m['title'],
                    'language':m['language'],'topic':m['topic'],
                    'chunk_index':m['chunk_index'],'url':m['url'],
                    'fragmento':m['text'][:2200],
                    'contiene_respuesta_semantica':'PENDIENTE_REVISION_MANUAL',
                    'notas':''
                })
        summary_rows.append({
            'question_id':qid,'tipo':'cross' if cross else 'monolingual',
            'question_language':qlang,'evidence_language':e_lang,
            'source_document_id':source_id,'gold_chunks_locales':','.join(map(str,sorted(gold_locals))),
            'existe_fuente':bool(source_indices),'gold_localizado':gold_found,
            'mejor_rango_documento':doc_rank,'mejor_rango_chunk_evidencia':gold_rank,
            'rango_cobertura_completa_evidencia':full_evidence_rank,
            'hit5_parcial':bool(gold_rank is not None and gold_rank<=5),
            'hit5_evidencia':bool(full_evidence_rank is not None and full_evidence_rank<=5),
            'hit10_evidencia':bool(full_evidence_rank is not None and full_evidence_rank<=10),
            'auditoria_exclusividad_semantica':'PENDIENTE_REVISION_HUMANA' if cross else 'NO_APLICA'
        })
        print(f'{qid}: documento rango {doc_rank}; primer chunk evidencia rango {gold_rank}; '
              f'cobertura completa rango {full_evidence_rank}; '
              f'Hit@5 completo={bool(full_evidence_rank is not None and full_evidence_rank<=5)}',flush=True)
    save_csv(out/'resumen_retrieval.csv',summary_rows,
             ['question_id','tipo','question_language','evidence_language','source_document_id',
              'gold_chunks_locales','existe_fuente','gold_localizado','mejor_rango_documento',
              'mejor_rango_chunk_evidencia','rango_cobertura_completa_evidencia',
              'hit5_parcial','hit5_evidencia','hit10_evidencia','auditoria_exclusividad_semantica'])
    save_csv(out/'top_global.csv',global_rows,
             ['question_id','rank','score','document_id','language','topic','title','chunk_index',
              'es_fuente_esperada','es_chunk_evidencia','url','fragmento'])
    save_csv(out/'revision_crosslingual_idioma_pregunta.csv',same_lang_rows,
             ['question_id','question','respuesta_esperada','rank_idioma_pregunta','rank_global','score',
              'document_id','title','language','topic','chunk_index','url','fragmento',
              'contiene_respuesta_semantica','notas'])
    hits=sum(1 for r in summary_rows if r['hit5_evidencia'])
    report={
       'corpus_sha256':manifest['sha256_corpus'], 'model':args.model,
       'documents':manifest['documents'],'chunks':manifest['chunks'],
       'chunks_by_language':manifest['chunks_by_language'],
       'questions':len(summary_rows),'hit5_piloto':round(hits/len(summary_rows),4),
       'results':summary_rows,
       'caveats':[
         'Las 5 preguntas forman un PILOTO, no son una medida de rendimiento estadísticamente representativa.',
         'Si la evidencia cruza un límite de chunk, Hit@5 evidencia exige recuperar TODOS los chunks implicados; Hit@5 parcial solo requiere uno.',
         'La ausencia de respuestas literales o de respuestas en el top-N del idioma de consulta no prueba exclusividad semántica.',
         'Revisar manualmente las evidencias en revision_crosslingual_idioma_pregunta.csv y ampliar búsqueda si hay ambigüedad.',
         'La búsqueda vectorial exhaustiva de este script es una línea base; aún falta comparar con FTS e híbrido en PostgreSQL.',
         'Repetir evaluación tras cambiar el corpus o los fragmentos.'
       ]
    }
    (out/'informe_semantico.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Hit@5 sobre chunks de evidencia del piloto: {hits}/{len(summary_rows)} (NO evaluación final).',flush=True)
    print('Revisar resultados en:',out.resolve(),flush=True)

if __name__=='__main__':
    main()
