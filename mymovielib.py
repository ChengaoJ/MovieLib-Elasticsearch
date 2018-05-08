from flask import Flask, render_template, request, Response, jsonify
from elasticsearch import Elasticsearch
from elasticsearch_dsl import Search, Q
from elasticsearch_dsl.aggs import A
import logging
import sys
import json

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

es = Elasticsearch(hosts=[{'host': 'localhost', 'port': 9200}])
app = Flask(__name__)

PAGE_SIZE = 8


def get_page_url(search, genre, sort, i):
    return '/movies?%s' % '&'.join(filter(lambda x: x, [search, genre, sort, 'page=%s' % i]))


def get_list_result(movies, max_page, **kwargs):
    page = int(kwargs.get('page', 1))
    search = 'search=%s' % kwargs.get('search') if kwargs.get('search') else ''
    genre = 'genre=%s' % kwargs.get('genre') if kwargs.get('genre') else ''
    sort = 'sort=%s' % kwargs.get('sort') if kwargs.get('sort') else ''
    pages = [(str(i), get_page_url(search, genre, sort, i))
             for i in range(page, min(page+5, max_page))]
    lastpage = {'num': max_page, 'url': get_page_url(search, genre, sort, max_page)}
    firstpage = {'num': 1, 'url': get_page_url(search, genre, sort, 1)}
    pageinfos = [{'num': p[0], 'url': p[1]} for p in pages] + [firstpage] + [lastpage]
    return render_template('review.html', movies=movies, genres=get_genre_agg(),
                           pages=pageinfos, search=kwargs.get('search'), genre=kwargs.get('genre'),
                           sort=kwargs.get('sort'), page=page)


@app.route('/test')
def test():
    return render_template('about.html')


@app.route('/')
@app.route('/movies')
def index(genre=None):
    # Get index first page items
    page = 1
    if request.args.get('page'):
        page = int(request.args.get('page'))
    genre = request.args.get('genre')
    sort = request.args.get('sort')
    search = request.args.get('search')
    print genre
    print page
    print search
    print sort
    s = Search(using=es)
    s = s.index('imdb')
    s = s.source(includes=['vote', 'title', 'poster', '_id'])
    s = s.query(Q('match_all'))
    if genre:
        s = s.query('bool', filter=[Q('term', genres=genre)])
    if sort:
        s = s.sort(sort)
    if search:
        s = s.query(Q('multi_match', query=search, fields=['title', 'summary', 'casts', 'creators', 'genres'])).extra(size=8)
    s = s[(page-1)*PAGE_SIZE:page*PAGE_SIZE]
    ret = s.execute()
    logger.debug(ret)
    movies, max_page = get_movies(ret.hits), int(ret.hits.total/PAGE_SIZE) + 1
    return get_list_result(movies, max_page, page=page, genre=genre, sort=sort, search=search)


def get_genre_agg():
    s = Search(using=es)
    s = s.index('imdb')
    s.aggs.bucket('genres', A('terms', field='genres'))
    ret = s.execute()
    # logger.debug('genre agg is %s', json.dumps(ret.aggs.to_dict(), indent=2))
    return [x['key'] for x in ret.aggs.to_dict()['genres']['buckets']]


@app.route('/movie/<string:mid>')
def movie_page(mid):
    s = Search(using=es)
    s = s.index('imdb')
    s = s.filter('term', _id=mid)
    ret = s.execute()
    return render_template('single.html', movie=get_movie_detail(ret.hits[0].to_dict()))


def get_movie_detail(hit):
    movie = hit
    movie['genres'] = '/'.join(movie['genres'])
    movie['creators'] = ', '.join(movie['creators'])
    movie['casts'] = ', '.join(movie['casts'])
    if movie['release_date']:
        movie['release_date'] = movie['release_date'].split('T')[0]
    else:
        movie['release_date'] = 'N/A'
    return movie


def get_movies(hits):
    for r in hits:
        r._d_['id'] = r.meta.id
    return [x.to_dict() for x in hits]


@app.route('/suggest/<string:input>')
def get_suggest(input):
    if not input:
        return None
    s = Search(using=es)
    s = s.index('imdb')
    s = s.suggest('suggestion', input, completion={'field': 'suggest'})
    s = s.source(False)
    logger.debug(s.to_dict())
    ret = s.execute()
    results = [x['text'] for x in ret.suggest.suggestion[0]['options']]
    logger.debug(results)
    return jsonify(result=results)
