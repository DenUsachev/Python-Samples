import json
import urllib2

import tornadoredis

from togetherapi.settings import MAX_GEO_RESPONSES
from togetherapi.utils import get_custom_logger, get_google_key

logger = get_custom_logger()
radius_threshold = 50000


# noinspection PyBroadException
class GeoRequest(object):
    def __init__(self, lat, lon, radius, lookup, exact_location):
        if lat is None:
            raise Exception('Latitude not set')
        else:
            self.lat = lat
        if lon is None:
            raise Exception('Longitude not set')
        else:
            self.lon = lon
        if radius is None or radius > radius_threshold:
            raise Exception('''Radius not set or exceeds Google API limitations''')
        self.exact = exact_location
        self.radius = radius
        self.lookup = lookup
        self.key = get_google_key()


# noinspection PyBroadException
class GeoResolver(object):
    @staticmethod
    def requestGoogleServices(request, user=None):
        try:
            lat_long = "%s,%s" % (request.lat, request.lon)
            # looking up for location's POI
            if request.lookup is not None:
                requested_url = \
                    'https://maps.googleapis.com/maps/api/place/nearbysearch/json?location=%s&radius=%d&name=%s&key=%s' % (
                        lat_long, request.radius, request.lookup, request.key)
            else:
                requested_url = \
                    'https://maps.googleapis.com/maps/api/place/nearbysearch/json?location=%s&radius=%d&key=%s' % (
                        lat_long, request.radius, request.key)
            fetched = urllib2.urlopen(requested_url.encode('utf-8')).read()
            poi_response = PoiLookupResult(fetched)

            # looking up for locations suggestions
            requested_url = \
                'https://maps.googleapis.com/maps/api/place/autocomplete/json?input={0}&types=geocode&location={1}&language=ru&key={2}'.format(
                    request.lookup, lat_long, request.key)
            fetched2 = urllib2.urlopen(requested_url.encode('utf-8')).read()
            suggestion_response = LocationSuggestionResult(fetched2)

            pois = poi_response.serialize()
            suggestions = suggestion_response.serialize()
            j_response = []
            plen = len(pois)
            slen = len(suggestions)
            if plen > 100 and slen > 100:
                mx = plen if plen - slen > 0 else slen
            else:
                mx = 100
            if request.exact:
                selection_limit = MAX_GEO_RESPONSES
            else:
                selection_limit = mx
            for i in range(selection_limit):
                mod = i % 2
                if mod == 0 or i == 0:
                    if plen > i:
                        j_response.append(pois[i])
                    elif slen > i:
                        j_response.append(suggestions[i])
                    else:
                        break
                else:
                    if slen > i:
                        j_response.append(suggestions[i])
                    elif plen > i:
                        j_response.append(pois[i])
                    else:
                        break
            # async feedback
            with tornadoredis.Client() as redis:
                if user.UserConnected:
                    logger.debug('Sending async data: {0}'.format(j_response))
                    redis.publish(user.UserPhone, json.dumps(j_response))
            return True
        except BaseException, ex:
            logger.error(ex.message)
            return False

    @staticmethod
    def requestObjectDetails(object_id):
        try:
            if object_id is None:
                raise Exception('Bad or empty object_id')
            else:
                requested_url = 'https://maps.googleapis.com/maps/api/place/details/json?placeid=%s&key=%s' % (
                    object_id, get_google_key())
                return urllib2.urlopen(requested_url.encode('utf-8')).read()
        except BaseException:
            return None


class GeoResult(object):
    logger = get_custom_logger()
    json_raw_results = None

    def serialize(self):
        pass

    def __init__(self, http_response):
        j_response = json.loads(http_response)
        if j_response is not None:
            self.json_raw_results = j_response
        else:
            raise BaseException('Unable to serialize HTTP-result from Google services')


# noinspection PyBroadException
class PoiLookupResult(GeoResult):
    def __init__(self, http_response):
        super(PoiLookupResult, self).__init__(http_response)

    def serialize(self):
        results = []
        try:
            for res in self.json_raw_results['results']:
                results.append({
                    'type': 1,
                    'lat': res['geometry']['location']['lat'],
                    'lng': res['geometry']['location']['lng'],
                    'icon': res['icon'],
                    'name': res['name'],
                    'vicinity': res['vicinity'],
                    'id': res['id'],
                    'place_id': res['place_id'],
                    'ref': res['reference'],
                    'rating': res.get('rating')
                })
        except BaseException, ex:
            self.logger.error(ex.message)
        finally:
            self.logger.debug(results)
            return results


# noinspection PyBroadException
class LocationSuggestionResult(GeoResult):
    def __init__(self, http_response):
        super(LocationSuggestionResult, self).__init__(http_response)

    def serialize(self):
        results = []
        try:
            for res in self.json_raw_results['predictions']:
                results.append({
                    'type': 2,
                    'vicinity': res['description'],
                    'id': res['id'],
                    'place_id': res['place_id'],
                    'ref': res['reference'],
                })
        except BaseException, ex:
            self.logger.error(ex.message)
        finally:
            self.logger.debug(results)
            return results
