import xbmc
import xbmcgui
import xbmcplugin
from urllib import urlencode
from resources.lib.vrtplayer import vrtplayer
from resources.lib.kodiwrappers import sortmethod

class KodiWrapper:

    def __init__(self, handle, url, addon):
        self._handle = handle
        self._url = url
        self._addon = addon

    def show_listing(self, list_items, sort=None):
        listing = []
        for title_item in list_items:
            list_item = xbmcgui.ListItem(label=title_item.title)
            url = self._url + '?' + urlencode(title_item.url_dictionary)
            list_item.setProperty('IsPlayable', str(title_item.is_playable))

            if title_item.thumbnail is not None:
                list_item.setArt({'thumb': title_item.thumbnail})

            list_item.setInfo('video', title_item.video_dictionary)

            listing.append((url, list_item, not title_item.is_playable))
        xbmcplugin.addDirectoryItems(self._handle, listing, len(listing))

        if sort is not None:
            kodi_sorts = {sortmethod.ALPHABET: xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE}
            kodi_sortmethod = kodi_sorts.get(sort)
            xbmcplugin.addSortMethod(self._handle, kodi_sortmethod)

        xbmcplugin.endOfDirectory(self._handle)

    def play(self, path, license_key):
        play_item = xbmcgui.ListItem(path=path)

        if path is not None and '/.mpd' in path:
            play_item.setProperty('inputstreamaddon', 'inputstream.adaptive')
            play_item.setProperty('inputstream.adaptive.manifest_type', 'mpd')
            play_item.setMimeType('application/dash+xml')
            play_item.setContentLookup(False)

        if license_key is not None:
            play_item.setProperty('inputstream.adaptive.license_type', 'com.widevine.alpha')
            play_item.setProperty('inputstream.adaptive.license_key', license_key)

        xbmcplugin.setResolvedUrl(self._handle, True, listitem=play_item)

    def show_ok_dialog(self, title, message):
        xbmcgui.Dialog().ok(self._addon.getAddonInfo('name'), title, message)

    def get_localized_string(self, string_id):
        return self._addon.getLocalizedString(string_id)

    def get_setting(self, setting_id ):
        return self._addon.getSetting(setting_id)

    def open_settings(self):
        self._addon.openSettings()

    def get_userdata_path(self):
        return xbmc.translatePath(self._addon.getAddonInfo('profile')).decode('utf-8')

    def log(self, message):
        xbmc.log(message, xbmc.LOGNOTICE)
