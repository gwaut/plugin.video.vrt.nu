# -*- coding: utf-8 -*-

# GNU General Public License v3.0 (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, unicode_literals
import json
import re

from resources.lib.helperobjects import apidata, streamurls

try:
    from urllib.parse import quote, unquote, urlencode
    from urllib.error import HTTPError
    from urllib.request import build_opener, install_opener, urlopen, ProxyHandler
except ImportError:
    from urllib import urlencode  # pylint: disable=ungrouped-imports
    from urllib2 import build_opener, install_opener, urlopen, ProxyHandler, quote, unquote, HTTPError


class StreamService:

    _VUPLAY_API_URL = 'https://api.vuplay.co.uk'
    _VUALTO_API_URL = 'https://media-services-public.vrt.be/vualto-video-aggregator-web/rest/external/v1'
    _CLIENT = 'vrtvideo'

    def __init__(self, _kodi, _tokenresolver):
        self._kodi = _kodi
        self._proxies = _kodi.get_proxies()
        install_opener(build_opener(ProxyHandler(self._proxies)))
        self._tokenresolver = _tokenresolver
        self._create_settings_dir()
        self._can_play_drm = _kodi.can_play_drm()
        self._license_url = None

    def _get_license_url(self):
        self._kodi.log_notice('URL get: ' + unquote(self._VUPLAY_API_URL), 'Verbose')
        self._license_url = json.loads(urlopen(self._VUPLAY_API_URL).read()).get('drm_providers', dict()).get('widevine', dict()).get('la_url')

    def _create_settings_dir(self):
        settingsdir = self._kodi.get_userdata_path()
        if not self._kodi.check_if_path_exists(settingsdir):
            self._kodi.make_dir(settingsdir)

    def _get_license_key(self, key_url, key_type='R', key_headers=None, key_value=None):
        ''' Generates a propery license key value

            # A{SSM} -> not implemented
            # R{SSM} -> raw format
            # B{SSM} -> base64 format
            # D{SSM} -> decimal format

            The generic format for a LicenseKey is:
            |<url>|<headers>|<key with placeholders|

            The Widevine Decryption Key Identifier (KID) can be inserted via the placeholder {KID}

            @type key_url: str
            @param key_url: the URL where the license key can be obtained

            @type key_type: str
            @param key_type: the key type (A, R, B or D)

            @type key_headers: dict
            @param key_headers: A dictionary that contains the HTTP headers to pass

            @type key_value: str
            @param key_value: i
            @return:
        '''
        header = ''
        if key_headers:
            header = urlencode(key_headers)

        if key_type in ('A', 'R', 'B'):
            key_value = key_type + '{SSM}'
        elif key_type == 'D':
            if 'D{SSM}' not in key_value:
                raise ValueError('Missing D{SSM} placeholder')
            key_value = quote(key_value)

        return '%s|%s|%s|' % (key_url, header, key_value)

    def _get_api_data(self, video):
        '''Get and prepare api data object'''
        video_url = video.get('video_url')
        video_id = video.get('video_id')
        publication_id = video.get('publication_id')
        # Prepare api_data for on demand streams by video_id and publication_id
        if video_id and publication_id:
            xvrttoken = self._tokenresolver.get_xvrttoken()
            api_data = apidata.ApiData(self._CLIENT, self._VUALTO_API_URL, video_id, publication_id + quote('$'), xvrttoken, False)
        # Prepare api_data for livestreams by video_id, e.g. vualto_strubru, vualto_mnm
        elif video_id and not video_url:
            api_data = apidata.ApiData(self._CLIENT, self._VUALTO_API_URL, video_id, '', None, True)
        # Webscrape api_data with video_id fallback
        elif video_url:
            api_data = self._webscrape_api_data(video_url) or apidata.ApiData(self._CLIENT, self._VUALTO_API_URL, video_id, '', None, True)
        return api_data

    def _webscrape_api_data(self, video_url):
        '''Scrape api data from VRT NU html page'''
        from bs4 import BeautifulSoup, SoupStrainer
        self._kodi.log_notice('URL get: ' + unquote(video_url), 'Verbose')
        html_page = urlopen(video_url).read()
        strainer = SoupStrainer('div', {'class': 'cq-dd-vrtvideo'})
        soup = BeautifulSoup(html_page, 'html.parser', parse_only=strainer)
        try:
            video_data = soup.find(lambda tag: tag.name == 'div' and tag.get('class') == ['vrtvideo']).attrs
        except Exception as e:
            # Web scraping failed, log error
            self._kodi.log_error('Web scraping api data failed: %s' % e)
            return None

        # Web scraping failed, log error
        if not video_data:
            self._kodi.log_error('Web scraping api data failed, empty video_data')
            return None

        # Store required html data attributes
        client = video_data.get('data-client')
        media_api_url = video_data.get('data-mediaapiurl')
        video_id = video_data.get('data-videoid')
        publication_id = video_data.get('data-publicationid', '')
        # Live stream or on demand
        if video_id is None:
            is_live_stream = True
            video_id = video_data.get('data-livestream')
            xvrttoken = None
        else:
            is_live_stream = False
            publication_id += quote('$')
            xvrttoken = self._tokenresolver.get_xvrttoken()

        if client is None or media_api_url is None or (video_id is None and publication_id is None):
            self._kodi.log_error('Web scraping api data failed, required attributes missing')
            return None

        return apidata.ApiData(client, media_api_url, video_id, publication_id, xvrttoken, is_live_stream)

    def _get_video_json(self, api_data):
        token_url = api_data.media_api_url + '/tokens'
        if api_data.is_live_stream:
            playertoken = self._tokenresolver.get_live_playertoken(token_url, api_data.xvrttoken)
        else:
            playertoken = self._tokenresolver.get_ondemand_playertoken(token_url, api_data.xvrttoken)

        # Construct api_url and get video json
        video_json = None
        if playertoken:
            api_url = api_data.media_api_url + '/videos/' + api_data.publication_id + \
                api_data.video_id + '?vrtPlayerToken=' + playertoken + '&client=' + api_data.client
            self._kodi.log_notice('URL get: ' + unquote(api_url), 'Verbose')
            try:
                video_json = json.loads(urlopen(api_url).read())
            except HTTPError as e:
                video_json = json.loads(e.read())

        return video_json

    def _handle_error(self, video_json):
        self._kodi.log_error(video_json.get('message'))
        message = self._kodi.localize(30054)
        self._kodi.show_ok_dialog('', message)

    @staticmethod
    def _fix_virtualsubclip(stream_dict, duration):
        '''VRT NU uses virtual subclips to provide on demand programs (mostly current affair programs)
           already from a livestream while or shortly after live broadcasting them.
           But this feature doesn't work always as expected because Kodi doesn't play the program from
           the beginning when the ending timestamp of the program is missing from the stream_url.
           When begintime is present in the stream_url and endtime is missing, we must add endtime
           to the stream_url so Kodi treats the program as an on demand program and starts the stream
           from the beginning like a real on demand program.'''
        from datetime import datetime, timedelta
        import dateutil.parser
        for key, value in stream_dict.items():
            begin = value.split('?t=')[1] if '?t=' in value else None
            if begin and len(begin) == 19:
                begin_time = dateutil.parser.parse(begin)
                end_time = begin_time + duration
                # If on demand program is not yet broadcasted completely,
                # use current time minus 5 seconds safety margin as endtime.
                now = datetime.utcnow()
                if end_time > now:
                    end_time = now - timedelta(seconds=5)
                stream_dict[key] = '-'.join((value, end_time.strftime('%Y-%m-%dT%H:%M:%S')))
        return stream_dict

    def get_stream(self, video, retry=False, api_data=None):
        '''Main streamservice function'''
        from datetime import timedelta
        if not video.get('video_id') and video.get('video_url'):
            return streamurls.StreamURLS(video.get('video_url'))
        if not api_data:
            api_data = self._get_api_data(video)

        vudrm_token = None
        video_json = self._get_video_json(api_data)
        if video_json:
            if 'drm' in video_json:
                vudrm_token = video_json.get('drm')
                target_urls = video_json.get('targetUrls')
                duration = timedelta(milliseconds=video_json.get('duration'))
                stream_dict = self._fix_virtualsubclip(dict(list([(x.get('type'), x.get('url')) for x in target_urls])), duration)
                return self._select_stream(stream_dict, vudrm_token)

            if video_json.get('code') in ('INCOMPLETE_ROAMING_CONFIG', 'INVALID_LOCATION'):
                self._kodi.log_error(video_json.get('message'))
                roaming_xvrttoken = self._tokenresolver.get_xvrttoken(True)
                if not retry and roaming_xvrttoken is not None:
                    # Delete cached playertokens
                    if api_data.is_live_stream:
                        self._kodi.delete_file(self._kodi.get_userdata_path() + 'live_vrtPlayerToken')
                    else:
                        self._kodi.delete_file(self._kodi.get_userdata_path() + 'ondemand_vrtPlayerToken')
                    # Update api_data with roaming_xvrttoken and try again
                    api_data.xvrttoken = roaming_xvrttoken
                    return self.get_stream(video, retry=True, api_data=api_data)
                message = self._kodi.localize(30053)
                self._kodi.show_ok_dialog('', message)
            else:
                self._handle_error(video_json)

        return None

    def _try_get_drm_stream(self, stream_dict, vudrm_token):
        if self._license_url is None:
            self._get_license_url()
        protocol = 'mpeg_dash'
        encryption_json = '{{"token":"{0}","drm_info":[D{{SSM}}],"kid":"{{KID}}"}}'.format(vudrm_token)
        license_key = self._get_license_key(key_url=self._license_url,
                                            key_type='D',
                                            key_value=encryption_json,
                                            key_headers={'Content-Type': 'text/plain;charset=UTF-8'})
        return streamurls.StreamURLS(stream_dict[protocol], license_key=license_key, use_inputstream_adaptive=True) if protocol in stream_dict else None

    def _select_stream(self, stream_dict, vudrm_token):
        stream_url = None
        protocol = None
        if vudrm_token and self._can_play_drm and self._kodi.get_setting('usedrm') == 'true':
            protocol = 'mpeg_dash drm'
            self._kodi.log_notice('Protocol: ' + protocol, 'Verbose')
            stream_url = self._try_get_drm_stream(stream_dict, vudrm_token)

        if vudrm_token and stream_url is None:
            protocol = 'hls_aes'
            self._kodi.log_notice('Protocol: ' + protocol, 'Verbose')
            stream_url = streamurls.StreamURLS(*self._select_hls_substreams(stream_dict[protocol])) if protocol in stream_dict else None

        if self._kodi.has_inputstream_adaptive_installed() and stream_url is None:
            protocol = 'mpeg_dash'
            self._kodi.log_notice('Protocol: ' + protocol, 'Verbose')
            stream_url = streamurls.StreamURLS(stream_dict[protocol], use_inputstream_adaptive=True) if protocol in stream_dict else None

        if stream_url is None:
            protocol = 'hls'
            self._kodi.log_notice('Protocol: ' + protocol, 'Verbose')
            # No if-else statement because this is the last resort stream selection
            stream_url = streamurls.StreamURLS(*self._select_hls_substreams(stream_dict[protocol]))

        return stream_url

    def _select_hls_substreams(self, master_hls_url):
        '''Select HLS substreams to speed up Kodi player start, workaround for slower kodi selection'''
        hls_variant_url = None
        subtitle_url = None
        hls_audio_id = None
        hls_subtitle_id = None
        hls_base_url = master_hls_url.split('.m3u8')[0]
        self._kodi.log_notice('URL get: ' + unquote(master_hls_url) + '?hd', 'Verbose')
        hls_playlist = urlopen(master_hls_url + '?hd').read()
        max_bandwidth = self._kodi.get_max_bandwidth()
        stream_bandwidth = None

        # Get hls variant url based on max_bandwith setting
        hls_variant_regex = re.compile(r'#EXT-X-STREAM-INF[:\w\-=,]*[:,]BANDWIDTH=([0-9]+)[\w\-=,.\"]+AUDIO=\"([\w-]+)\"[\w\-=,.\"]?(?:SUBTITLES=\"([\w]+)\")?[\w\-=,.\"]+[\r\n]([\w:\/\-.=?&]+)')
        # reverse sort by bandwidth
        for match in sorted(re.finditer(hls_variant_regex, hls_playlist), key=lambda m: int(m.group(1)), reverse=True):
            stream_bandwidth = int(match.group(1)) // 1000
            if max_bandwidth == 0 or stream_bandwidth < max_bandwidth:
                if match.group(4).startswith('http'):
                    hls_variant_url = match.group(4)
                else:
                    hls_variant_url = hls_base_url + match.group(4)
                hls_audio_id = match.group(2)
                hls_subtitle_id = match.group(3)
                break

        if not hls_variant_url:
            message = self._kodi.localize(30057) % (str(max_bandwidth), stream_bandwidth)
            self._kodi.show_ok_dialog('', message)
            self._kodi.open_settings()

        # Get audio url
        if hls_audio_id:
            audio_regex = re.compile(r'#EXT-X-MEDIA:TYPE=AUDIO[\w\-=,\.\"\/]+GROUP-ID=\"' + hls_audio_id + r'\"[\w\-=,\.\"\/]+URI=\"([\w\-=]+)\.m3u8\"')
            match_audio = re.search(audio_regex, hls_playlist)
            if match_audio:
                hls_variant_url = hls_base_url + match_audio.group(1) + '-' + hls_variant_url.split('-')[-1]

        # Get subtitle url, works only for on demand streams
        if self._kodi.get_setting('showsubtitles') == 'true' and '/live/' not in master_hls_url and hls_subtitle_id:
            subtitle_regex = re.compile(r'#EXT-X-MEDIA:TYPE=SUBTITLES[\w\-=,\.\"\/]+GROUP-ID=\"' + hls_subtitle_id + r'\"[\w\-=,\.\"\/]+URI=\"([\w\-=]+)\.m3u8\"')
            match_subtitle = re.search(subtitle_regex, hls_playlist)
            if match_subtitle:
                subtitle_url = hls_base_url + match_subtitle.group(1) + '.webvtt'

        return hls_variant_url, subtitle_url
