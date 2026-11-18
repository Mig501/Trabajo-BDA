#!/usr/bin/env python3
"""Banco de preguntas RAG basado en hechos documentados, NO validación final de retrieval.
Usar corpus Wikipedia ES/EN congelado. Las 5 preguntas originales no se incluyen.
"""
import argparse,csv,hashlib,json,re,unicodedata
from collections import Counter,defaultdict
from pathlib import Path

# Datos redactados a partir de los artículos descargados. Las anclas y respuestas
# se validan contra el texto EXACTO y el revision_id del corpus indicado.
# (split, tipo, idioma_pregunta, tema, document_id, pregunta, respuesta, ancla)
SPECS = [
# TEST ES -> ES: 5 por tema
('test','mono','es','astronomia','wiki:es:14073','¿A qué profundidad bajo el agua se descubrió el mecanismo de Anticitera cerca de Glyfadia?','45 metros','descubierto a 45 metros'),
('test','mono','es','astronomia','wiki:es:124019','¿Qué otros dos fundadores acompañaron a Carl Sagan en la creación de la Sociedad Planetaria en 1980?','Bruce Murray y Louis Friedman','Fue fundada en 1980'),
('test','mono','es','astronomia','wiki:es:101412','¿A qué instituto se incorporó Hannes Alfvén en 1937?','Instituto Nobel de Física','pasando en 1937'),
('test','mono','es','astronomia','wiki:es:7343347','¿Qué asociación encargó a Mary Adela Blagg cotejar los elementos lunares en 1905?','Asociación Internacional de Academias','En 1905 fue nombrada'),
('test','mono','es','astronomia','wiki:es:7997624','¿A qué país se dirigía la expedición rusa de 1805 en la que participó Theodor von Schubert?','China','en 1805 participó'),
('test','mono','es','fisica','wiki:es:11473839','¿De qué país es un anagrama el apellido Einasto elegido por el padre de Jaan Einasto?','Estonia','nombre «Einasto»'),
('test','mono','es','fisica','wiki:es:96352','¿Qué instituto fundó Walther Nernst en Gotinga en 1895?','Instituto de Química, Física y Electroquímica','en 1895, fundó'),
('test','mono','es','fisica','wiki:es:3586362','¿Qué propiedad de la montaña Schiehallion facilitó el cálculo de su volumen durante el experimento gravitatorio?','simetría de su ladera este-oeste','por la simetría'),
('test','mono','es','fisica','wiki:es:8934141','¿En qué año se publicó el primer artículo científico firmado únicamente por Peter Guthrie Tait?','1860','únicamente el nombre de Tait'),
('test','mono','es','fisica','wiki:es:9209263','¿Qué instrumentos desarrolló Leona Woods para los análisis del reactor Chicago Pile-1?','contadores geiger','Leona desarrolló'),
('test','mono','es','matematicas','wiki:es:3157439','¿De qué sociedad matemática editó José Adem el boletín desde 1956?','Sociedad Matemática Mexicana','edición del boletín'),
('test','mono','es','matematicas','wiki:es:3027253','¿En qué ciudad fundó Federico Commandino una escuela de matemáticas?','Urbino','Fundó en Urbino'),
('test','mono','es','matematicas','wiki:es:6373264','¿Cómo se titulaba el periódico de José Ignacio Bartolache con noticias sobre física y medicina?','El Mercurio Volante','Publicó El Mercurio Volante'),
('test','mono','es','matematicas','wiki:es:11993','¿Cómo se titulaba el estudio que Santiago Antúnez de Mayolo publicó en 1932 anticipando la existencia del positrón?','Los tres elementos constitutivos de la materia','Los tres elementos constitutivos de la materia'),
('test','mono','es','matematicas','wiki:es:9696105','¿En qué ferrocarril colaboró George Parker Bidder en el diseño de un método para separar vagones sin detener el tren?','Ferrocarril de Blackwall','Ferrocarril de Blackwall'),
('test','mono','es','quimica','wiki:es:11418278','¿De qué elemento demostraron Stefanie Horovitz y Hönigschmid que era isótopo el ionio?','torio','el ionio'),
('test','mono','es','quimica','wiki:es:201058','¿Qué hermano ayudó a Juan José Delhuyar a obtener wolframio en 1783?','Fausto','ayudado por su hermano'),
('test','mono','es','quimica','wiki:es:7333930','¿En qué año ingresó Olga Kennard en la Royal Society de Londres?','1987','En 1987 se convirtió'),
('test','mono','es','quimica','wiki:es:10297843','¿En qué universidad dirigió Norman Greenwood el Departamento de Química Inorgánica y Estructural a partir de 1971?','Universidad de Leeds','Departamento de Química Inorgánica'),
('test','mono','es','quimica','wiki:es:700876','¿En qué país se desarrolló en 1968 la idea de la Olimpiada Internacional de Química?','Checoslovaquia','Checoslovaquia en 1968'),
# TEST EN -> EN: 5 por tema
('test','mono','en','astronomia','wiki:en:180079','In which journal was Karl Jansky’s 1933 paper on extraterrestrial electrical disturbances published?','Proceedings of the Institute of Radio Engineers','In October 1933'),
('test','mono','en','astronomia','wiki:en:7547036','Which organisation published most of Agnes Giberne’s books intended for young adolescent girls?','Religious Tract Society','mainly published by the Religious Tract Society'),
('test','mono','en','astronomia','wiki:en:35731918','Who discovered asteroid 107638 Wendyfreedman at the Junk Bond Observatory in 2001?','David Healy','discovered by David Healy'),
('test','mono','en','astronomia','wiki:en:43516991','In which city was David Friesenhausen’s book eventually published in 1820?','Vienna','published in Vienna'),
('test','mono','en','astronomia','wiki:en:25955458','To which school of astronomy and mathematics did Sankara Varman belong?','Kerala school of astronomy and mathematics','Kerala school of astronomy and mathematics'),
('test','mono','en','fisica','wiki:en:145319','Which Indian mathematician had received a Trinity Fellowship before Chandrasekhar was elected in 1933?','Srinivasa Ramanujan','Srinivasa Ramanujan'),
('test','mono','en','fisica','wiki:en:65981704','Which publisher released David C. Cassidy’s book Beyond Uncertainty in 2009?','Bellevue Literary Press','Bellevue Literary Press'),
('test','mono','en','fisica','wiki:en:164975','Which English physician is credited with inventing the terrella model used in early studies of magnetism?','William Gilbert','William Gilbert'),
('test','mono','en','fisica','wiki:en:725441','In what year did George Atwood invent the Atwood machine for laboratory experiments on motion?','1784','invented in 1784'),
('test','mono','en','fisica','wiki:en:35646024','Which Dutch museum houses the Instrument Room containing its historic Cabinet of Physics?','Teylers Museum','Teylers Museum'),
('test','mono','en','matematicas','wiki:en:43531998','Which former postdoctoral researcher worked with Thomas Hou on the multiscale finite element method?','Xiao-Hui Wu','Xiao-Hui Wu'),
('test','mono','en','matematicas','wiki:en:17318580','How many papers by Philip Kelland are listed in the Royal Society Catalogue of Scientific Papers?','28','28 papers'),
('test','mono','en','matematicas','wiki:en:63279733','Which journal dedicated a special issue to Mirka Miller in 2017?','Australasian Journal of Combinatorics','Australasian Journal of Combinatorics'),
('test','mono','en','matematicas','wiki:en:30849196','Which two Cambridge examination distinctions did Numa Edward Hartog achieve in 1869?','Senior Wrangler and Smith\'s Prizeman','Senior Wrangler and Smith'),
('test','mono','en','matematicas','wiki:en:58334483','Who supervised Bruno Nachtergaele’s 1987 doctorate on the spin–Boson model?','André Verbeure','André Verbeure'),
('test','mono','en','quimica','wiki:en:457891','At which naval facility did Philip Abelson invent the liquid thermal diffusion isotope-separation technique later used at Oak Ridge?','Philadelphia Navy Yard','Philadelphia Navy Yard'),
('test','mono','en','quimica','wiki:en:4173711','Who coined the name “molecular biology” at the Rockefeller Foundation in 1938?','Warren Weaver','Warren Weaver'),
('test','mono','en','quimica','wiki:en:381585','At which research laboratory was the Hevesy Laboratory founded in May 2005?','Risø National Laboratory for Sustainable Energy','Risø National Laboratory'),
('test','mono','en','quimica','wiki:en:13660531','Which research area occupied Heinz Gerischer during the 1949–1955 period in Berlin and Göttingen?','electrode kinetics','electrode kinetics'),
('test','mono','en','quimica','wiki:en:82788949','In which year was electroanalytical chemist Charles N. Reilley elected to the National Academy of Sciences?','1977','elected to the National Academy'),
# TEST CROSS ES -> EN: source documents distinct from monolingual questions
('test','cross','es','astronomia','wiki:en:67267891','¿Qué centro de investigación de la Universidad de Berna dirigió anteriormente la astrofísica Kathrin Altwegg?','Center for Space and Habitability','Center for Space and Habitability'),
('test','cross','es','astronomia','wiki:en:1529563','¿Qué astrónomo descubrió el asteroide 378 Holmia el 6 de diciembre de 1893?','Auguste Charlois','discovered by French astronomer Auguste Charlois'),
('test','cross','es','fisica','wiki:en:75949013','¿En qué colegio universitario de Cambridge se celebró la fiesta para viajeros en el tiempo de Stephen Hawking en junio de 2009?','Gonville and Caius College','Gonville and Caius College'),
('test','cross','es','matematicas','wiki:en:53776585','¿En qué localidad de la Selva Negra se encuentra el museo MiMa de mineralogía y matemáticas?','Oberwolfach','in Oberwolfach'),
('test','cross','es','quimica','wiki:en:63095115','¿En qué publicación del CSIC escribió Jenara Vicenta Arnal Yarza materiales dirigidos al profesorado de primaria?','Boletín Bibliográfico del CSIC','Boletín Bibliográfico del CSIC'),
# TEST CROSS EN -> ES
('test','cross','en','astronomia','wiki:es:4406544','Which UNAM institute appointed Luis Felipe Rodríguez as its director in 1980?','Instituto de Astronomía de la UNAM','Instituto de Astronomía de la UNAM'),
('test','cross','en','fisica','wiki:es:6599740','For which Alpine tunnel did Jean-Daniel Colladon propose his compressed-air excavation system?','túnel del Mont Cenis','túnel del Mont Cenis'),
('test','cross','en','matematicas','wiki:es:9873552','In which scientific journal was Adam Adamandy Kochański’s Observationes Cyclometricae published in 1685?','Acta Eruditorum','Acta Eruditorum'),
('test','cross','en','quimica','wiki:es:10388931','What property of beer did Gabriela Basařová study in her 1980 doctoral dissertation?','estabilidad coloidal de la cerveza','estabilidad coloidal de la cerveza'),
('test','cross','en','matematicas','wiki:es:11331843','What was the original title of Nikolai Delaunay’s manual on the independent study of higher mathematics and mechanics, published in 1900?','Manual para el estudio independiente de las matemáticas superiores y la mecánica','Manual para el estudio independiente de las matemáticas superiores y la mecánica'),
# DEV 10, other sources when possible
('dev','mono','es','astronomia','wiki:es:4390388','¿En qué año fue reconocido Francisco Duarte como fellow de la Optical Society of America?','1993','Optical Society of America (1993)'),
('dev','mono','es','fisica','wiki:es:403919','¿Qué centro de física teórica comenzó a dirigir Abdus Salam al fundarse en 1964?','Centro Internacional de Física Teórica','Centro Internacional de Física Teórica'),
('dev','mono','es','matematicas','wiki:es:348029','¿Qué asteroide fue nombrado en honor del matemático Pável Urysón?','(13673) Urysohn','(13673) Urysohn'),
('dev','mono','es','quimica','wiki:es:10629150','¿En qué año publicó Auguste Bravais su trabajo temprano sobre correlación estadística?','1844','En 1844 publicó'),
('dev','mono','es','astronomia','wiki:es:8114496','¿En qué año se fundó la academia científica de la que Pehr Wilhelm Wargentin fue primer secretario?','1739','había sido fundada en 1739'),
('dev','mono','en','astronomia','wiki:en:3753089','Who wrote the 1899 book Star-Names and Their Meanings about the lore of stellar names?','Richard Hinckley Allen','Richard Hinckley Allen'),
('dev','mono','en','fisica','wiki:en:3464501','At which national laboratory was the Cosmotron proton synchrotron located?','Brookhaven National Laboratory','Brookhaven National Laboratory'),
('dev','mono','en','matematicas','wiki:en:69736905','In which year did Klein’s Encyclopedia of Mathematical Sciences feature a hundred-page article on triangle geometry?','1914','published in 1914'),
('dev','mono','en','quimica','wiki:en:3265664','Who suggested contact tension in 1800 as an explanation for the operation of a voltaic pile?','Alessandro Volta','Alessandro Volta in 1800'),
('dev','mono','en','matematicas','wiki:en:7315901','Which Chinese mathematician found the approximation of pi named Milü?','Zu Chongzhi','Zu Chongzhi'),
]

def read_docs(path):
    docs={}
    with Path(path).open(encoding='utf-8') as fh:
        for ln,line in enumerate(fh,1):
            if not line.strip():continue
            d=json.loads(line); key=d['document_id']
            if key in docs:raise ValueError(f'Documento repetido {key}, línea {ln}')
            docs[key]=d
    return docs

def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD',s.casefold()) if not unicodedata.combining(c))

def quote_for(d,anchor,answer):
    txt=d['text']; lower=txt.casefold(); aa=lower.find(anchor.casefold()); bb=lower.find(answer.casefold())
    if aa<0:raise ValueError(f'{d["document_id"]}: ancla ausente: {anchor}')
    # Buscar respuesta próxima al ancla (no una aparición arbitraria en otro apartado)
    near=[m.start() for m in re.finditer(re.escape(answer.casefold()),lower) if abs(m.start()-aa)<500]
    if not near:
        raise ValueError(f'{d["document_id"]}: respuesta no localizada cerca de ancla: {anchor} | {answer}')
    bb=min(near,key=lambda p:abs(p-aa))
    start=max(0,min(aa,bb)-90)
    end=min(len(txt),max(aa+len(anchor),bb+len(answer))+90)
    # Ajustar a palabras: al menos un pasaje literal que contenga el ancla y la respuesta.
    while start>0 and not txt[start-1].isspace():start-=1
    while end<len(txt) and not txt[end].isspace():end+=1
    return txt[start:end].strip()

def main():
    p=argparse.ArgumentParser(description='Construye banco DEV 10 + TEST 50, con evidencias verificadas en corpus local.')
    p.add_argument('--corpus',default='data/corpus_wikipedia_ciencia/corpus_candidato.jsonl')
    p.add_argument('--out',default='data/evaluacion/banco_v1')
    p.add_argument('--allow-mismatch',action='store_true',help='Permite corpus distinto (con auditoría posterior obligatoria)')
    args=p.parse_args()
    raw=Path(args.corpus).read_bytes();sha=hashlib.sha256(raw).hexdigest()
    expected='12a4486e2ba6fde7c9548751306fceb4870794c6fda36276880144cf45f99304'
    if sha!=expected and not args.allow_mismatch:raise ValueError(f'Corpus distinto del auditado (hash {sha}); revisa --corpus.')
    docs=read_docs(args.corpus)
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    fields=['question_id','split','question','question_language','topic','question_type','expected_answer','gold_document_id','gold_document_language','evidence_quote','gold_chunk_ids','other_relevant_chunk_ids','source_title','source_url','source_revision_id','crosslingual_status','same_language_audit','metadata_filter_json','notes']
    rows=[];audit=[];counter=Counter()
    for split,typ,ql,topic,docid,question,answer,anchor in SPECS:
        if docid not in docs: raise ValueError('No existe documento fuente '+docid)
        d=docs[docid]
        if d['topic']!=topic:raise ValueError('Tema no coincide '+docid)
        if (ql==d['language']) != (typ=='mono'):raise ValueError('Tipo/idioma contradictorios '+docid)
        ev=quote_for(d,anchor,answer)
        n=counter[split];counter[split]+=1
        qid=('D' if split=='dev' else 'T')+f'{n+1:02d}'
        rows.append(dict(question_id=qid,split=split,question=question,question_language=ql,topic=topic,question_type=typ,expected_answer=answer,gold_document_id=docid,gold_document_language=d['language'],evidence_quote=ev,gold_chunk_ids='[]',other_relevant_chunk_ids='[]',source_title=d['title'],source_url=d['url'],source_revision_id=d['revision_id'],crosslingual_status='CANDIDATE_REQUIRES_SEMANTIC_REVIEW' if typ=='cross' else 'NO_APLICA',same_language_audit='PENDIENTE' if typ=='cross' else 'NO_APLICA',metadata_filter_json='{}',notes='Borrador con respuesta literal; revisión humana y retrieval todavía pendientes'))
    # Auditoría literal sobre TODOS los documentos del idioma de consulta. No implica equivalencia semántica.
    lower_by_lang={l:[(i,norm(d['text'])) for i,d in docs.items() if d['language']==l] for l in ('es','en')}
    for r in rows:
        hits=[]
        if r['question_type']=='cross':
            answer=norm(r['expected_answer'])
            # Palabras únicas completas para minimizar falsos positivos por subcadenas.
            pat=re.compile(r'(?<!\w)'+re.escape(answer)+r'(?!\w)')
            hits=[docid for docid,text in lower_by_lang[r['question_language']] if pat.search(text)]
            r['same_language_audit']=f'COINCIDENCIAS_LITERALES={len(hits)}; AUDITORIA_SEMANTICA_PENDIENTE'
        audit.append({'question_id':r['question_id'],'split':r['split'],'type':r['question_type'],
            'same_language_exact_matches':len(hits),'same_language_document_ids':'|'.join(hits[:20]),
            'comment':'La ausencia de coincidencias NO valida cross-lingual.' if r['question_type']=='cross' else 'No aplica'})
    with (out/'preguntas_candidatas.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    with (out/'auditoria_literal.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(audit[0]));w.writeheader();w.writerows(audit)
    counts=Counter((r['split'],r['question_language'],r['gold_document_language']) for r in rows)
    report={'corpus_sha256':sha,'documents':len(docs),'test_questions':counter['test'],'dev_questions':counter['dev'],
            'counts':{ '/'.join(k):v for k,v in sorted(counts.items())},
            'unique_source_documents':len({r['gold_document_id'] for r in rows}),
            'source_document_reuse':{d:n for d,n in Counter(r['gold_document_id'] for r in rows).items() if n>1},
            'cross_question_literal_flags':{a['question_id']:a['same_language_exact_matches'] for a in audit if a['type']=='cross'},
            'status':'PREGUNTAS_CANDIDATAS_NO_VERIFICADAS_FINALMENTE',
            'warnings':['Verificar respuesta, evidencia y formulación manualmente.',
                        'Auditar cross-lingual SEMANTICAMENTE en todos los documentos del idioma origen, no solo literalmente.',
                        'Anotar TODOS los chunks relevantes, no solo el documento gold.',
                        'Evaluar test solo después de fijar parámetros en dev.']}
    (out/'informe_banco.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
