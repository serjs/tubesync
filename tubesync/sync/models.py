import os
import uuid
import json
from datetime import datetime
from pathlib import Path
from django.conf import settings
from django.db import models
from django.core.files.storage import FileSystemStorage
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from common.errors import NoFormatException
from .youtube import (get_media_info as get_youtube_media_info,
                      download_media as download_youtube_media)
from .utils import seconds_to_timestr, parse_media_format
from .matching import (get_best_combined_format, get_best_audio_format, 
                       get_best_video_format)


media_file_storage = FileSystemStorage(location=settings.DOWNLOAD_ROOT)


class Source(models.Model):
    '''
        A Source is a source of media. Currently, this is either a YouTube channel
        or a YouTube playlist.
    '''

    SOURCE_TYPE_YOUTUBE_CHANNEL = 'c'
    SOURCE_TYPE_YOUTUBE_PLAYLIST = 'p'
    SOURCE_TYPES = (SOURCE_TYPE_YOUTUBE_CHANNEL, SOURCE_TYPE_YOUTUBE_PLAYLIST)
    SOURCE_TYPE_CHOICES = (
        (SOURCE_TYPE_YOUTUBE_CHANNEL, _('YouTube channel')),
        (SOURCE_TYPE_YOUTUBE_PLAYLIST, _('YouTube playlist')),
    )

    SOURCE_RESOLUTION_360P = '360p'
    SOURCE_RESOLUTION_480P = '480p'
    SOURCE_RESOLUTION_720P = '720p'
    SOURCE_RESOLUTION_1080P = '1080p'
    SOURCE_RESOLUTION_1440P = '1440p'
    SOURCE_RESOLUTION_2160P = '2160p'
    SOURCE_RESOLUTION_4320P = '4320p'
    SOURCE_RESOLUTION_AUDIO = 'audio'
    SOURCE_RESOLUTIONS = (SOURCE_RESOLUTION_360P, SOURCE_RESOLUTION_480P,
                          SOURCE_RESOLUTION_720P, SOURCE_RESOLUTION_1080P,
                          SOURCE_RESOLUTION_1440P, SOURCE_RESOLUTION_2160P,
                          SOURCE_RESOLUTION_4320P, SOURCE_RESOLUTION_AUDIO)
    SOURCE_RESOLUTION_CHOICES = (
        (SOURCE_RESOLUTION_360P, _('360p (SD)')),
        (SOURCE_RESOLUTION_480P, _('480p (SD)')),
        (SOURCE_RESOLUTION_720P, _('720p (HD)')),
        (SOURCE_RESOLUTION_1080P, _('1080p (Full HD)')),
        (SOURCE_RESOLUTION_1440P, _('1440p (2K)')),
        (SOURCE_RESOLUTION_2160P, _('2160p (4K)')),
        (SOURCE_RESOLUTION_4320P, _('4320p (8K)')),
        (SOURCE_RESOLUTION_AUDIO, _('Audio only')),
    )
    RESOLUTION_MAP = {
        SOURCE_RESOLUTION_360P: 360,
        SOURCE_RESOLUTION_480P: 480,
        SOURCE_RESOLUTION_720P: 720,
        SOURCE_RESOLUTION_1080P: 1080,
        SOURCE_RESOLUTION_1440P: 1440,
        SOURCE_RESOLUTION_2160P: 2160,
        SOURCE_RESOLUTION_4320P: 4320,
    }

    SOURCE_VCODEC_AVC1 = 'AVC1'
    SOURCE_VCODEC_VP9 = 'VP9'
    SOURCE_VCODECS = (SOURCE_VCODEC_AVC1, SOURCE_VCODEC_VP9)
    SOURCE_VCODECS_PRIORITY = (SOURCE_VCODEC_VP9, SOURCE_VCODEC_AVC1)
    SOURCE_VCODEC_CHOICES = (
        (SOURCE_VCODEC_AVC1, _('AVC1 (H.264)')),
        (SOURCE_VCODEC_VP9, _('VP9')),
    )

    SOURCE_ACODEC_MP4A = 'MP4A'
    SOURCE_ACODEC_OPUS = 'OPUS'
    SOURCE_ACODECS = (SOURCE_ACODEC_MP4A, SOURCE_ACODEC_OPUS)
    SOURCE_ACODEC_PRIORITY = (SOURCE_ACODEC_OPUS, SOURCE_ACODEC_MP4A)
    SOURCE_ACODEC_CHOICES = (
        (SOURCE_ACODEC_MP4A, _('MP4A')),
        (SOURCE_ACODEC_OPUS, _('OPUS')),
    )

    FALLBACK_FAIL = 'f'
    FALLBACK_NEXT_BEST = 'n'
    FALLBACK_NEXT_BEST_HD = 'h'
    FALLBACKS = (FALLBACK_FAIL, FALLBACK_NEXT_BEST, FALLBACK_NEXT_BEST_HD)
    FALLBACK_CHOICES = (
        (FALLBACK_FAIL, _('Fail, do not download any media')),
        (FALLBACK_NEXT_BEST, _('Get next best resolution or codec instead')),
        (FALLBACK_NEXT_BEST_HD, _('Get next best resolution but at least HD'))
    )

    # Fontawesome icons used for the source on the front end
    ICONS = {
        SOURCE_TYPE_YOUTUBE_CHANNEL: '<i class="fab fa-youtube"></i>',
        SOURCE_TYPE_YOUTUBE_PLAYLIST: '<i class="fab fa-youtube"></i>',
    }
    # Format to use to display a URL for the source
    URLS = {
        SOURCE_TYPE_YOUTUBE_CHANNEL: 'https://www.youtube.com/c/{key}',
        SOURCE_TYPE_YOUTUBE_PLAYLIST: 'https://www.youtube.com/playlist?list={key}',
    }
    # Callback functions to get a list of media from the source
    INDEXERS = {
        SOURCE_TYPE_YOUTUBE_CHANNEL: get_youtube_media_info,
        SOURCE_TYPE_YOUTUBE_PLAYLIST: get_youtube_media_info,
    }
    # Field names to find the media ID used as the key when storing media
    KEY_FIELD = {
        SOURCE_TYPE_YOUTUBE_CHANNEL: 'id',
        SOURCE_TYPE_YOUTUBE_PLAYLIST: 'id',
    }

    class IndexSchedule(models.IntegerChoices):
        EVERY_HOUR = 3600, _('Every hour')
        EVERY_2_HOURS = 7200, _('Every 2 hours')
        EVERY_3_HOURS = 10800, _('Every 3 hours')
        EVERY_4_HOURS = 14400, _('Every 4 hours')
        EVERY_5_HOURS = 18000, _('Every 5 hours')
        EVERY_6_HOURS = 21600, _('Every 6 hours')
        EVERY_12_HOURS = 43200, _('Every 12 hours')
        EVERY_24_HOURS = 86400, _('Every 24 hours')

    uuid = models.UUIDField(
        _('uuid'),
        primary_key=True,
        editable=False,
        default=uuid.uuid4,
        help_text=_('UUID of the source')
    )
    created = models.DateTimeField(
        _('created'),
        auto_now_add=True,
        db_index=True,
        help_text=_('Date and time the source was created')
    )
    last_crawl = models.DateTimeField(
        _('last crawl'),
        db_index=True,
        null=True,
        blank=True,
        help_text=_('Date and time the source was last crawled')
    )
    source_type = models.CharField(
        _('source type'),
        max_length=1,
        db_index=True,
        choices=SOURCE_TYPE_CHOICES,
        default=SOURCE_TYPE_YOUTUBE_CHANNEL,
        help_text=_('Source type')
    )
    key = models.CharField(
        _('key'),
        max_length=100,
        db_index=True,
        unique=True,
        help_text=_('Source key, such as exact YouTube channel name or playlist ID')
    )
    name = models.CharField(
        _('name'),
        max_length=100,
        db_index=True,
        unique=True,
        help_text=_('Friendly name for the source, used locally in TubeSync only')
    )
    directory = models.CharField(
        _('directory'),
        max_length=100,
        db_index=True,
        unique=True,
        help_text=_('Directory name to save the media into')
    )
    index_schedule = models.IntegerField(
        _('index schedule'),
        choices=IndexSchedule.choices,
        db_index=True,
        default=IndexSchedule.EVERY_6_HOURS,
        help_text=_('Schedule of how often to index the source for new media')
    )
    delete_old_media = models.BooleanField(
        _('delete old media'),
        default=False,
        help_text=_('Delete old media after "days to keep" days?')
    )
    days_to_keep = models.PositiveSmallIntegerField(
        _('days to keep'),
        default=14,
        help_text=_('If "delete old media" is ticked, the number of days after which '
                    'to automatically delete media')
    )
    source_resolution = models.CharField(
        _('source resolution'),
        max_length=8,
        db_index=True,
        choices=SOURCE_RESOLUTION_CHOICES,
        default=SOURCE_RESOLUTION_1080P,
        help_text=_('Source resolution, desired video resolution to download')
    )
    source_vcodec = models.CharField(
        _('source video codec'),
        max_length=8,
        db_index=True,
        choices=SOURCE_VCODEC_CHOICES,
        default=SOURCE_VCODEC_VP9,
        help_text=_('Source video codec, desired video encoding format to download (ignored if "resolution" is audio only)')
    )
    source_acodec = models.CharField(
        _('source audio codec'),
        max_length=8,
        db_index=True,
        choices=SOURCE_ACODEC_CHOICES,
        default=SOURCE_ACODEC_OPUS,
        help_text=_('Source audio codec, desired audio encoding format to download')
    )
    prefer_60fps = models.BooleanField(
        _('prefer 60fps'),
        default=True,
        help_text=_('Where possible, prefer 60fps media for this source')
    )
    prefer_hdr = models.BooleanField(
        _('prefer hdr'),
        default=False,
        help_text=_('Where possible, prefer HDR media for this source')
    )
    fallback = models.CharField(
        _('fallback'),
        max_length=1,
        db_index=True,
        choices=FALLBACK_CHOICES,
        default=FALLBACK_NEXT_BEST_HD,
        help_text=_('What do do when media in your source resolution and codecs is not available')
    )
    has_failed = models.BooleanField(
        _('has failed'),
        default=False,
        help_text=_('Source has failed to index media')
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _('Source')
        verbose_name_plural = _('Sources')

    @property
    def icon(self):
        return self.ICONS.get(self.source_type)

    @property
    def is_audio(self):
        return self.source_resolution == self.SOURCE_RESOLUTION_AUDIO

    @property
    def is_video(self):
        return not self.is_audio

    @property
    def extension(self):
        '''
            The extension is also used by youtube-dl to set the output container. As
            it is possible to quite easily pick combinations of codecs and containers
            which are invalid (e.g. OPUS audio in an MP4 container) just set this for
            people. All video is set to mkv containers, audio-only is set to m4a or ogg
            depending on audio codec.
        '''
        if self.is_audio:
            if self.source_acodec == self.SOURCE_ACODEC_MP4A:
                return 'm4a'
            elif self.source_acodec == self.SOURCE_ACODEC_OPUS:
                return 'ogg'
            else:
                raise ValueError('Unable to choose audio extension, uknown acodec')
        else:
            return 'mkv'

    @classmethod
    def create_url(obj, source_type, key):
        url = obj.URLS.get(source_type)
        return url.format(key=key)

    @property
    def url(self):
        return Source.create_url(self.source_type, self.key)

    @property
    def format_summary(self):
        if self.source_resolution == Source.SOURCE_RESOLUTION_AUDIO:
            vc = 'none'
        else:
            vc = self.source_vcodec
        ac = self.source_acodec
        f = ' 60FPS' if self.is_video and self.prefer_60fps else ''
        h = ' HDR' if self.is_video and self.prefer_hdr else ''
        return f'{self.source_resolution} (video:{vc}, audio:{ac}){f}{h}'.strip()

    @property
    def directory_path(self):
        download_dir = Path(media_file_storage.location)
        if self.source_resolution == self.SOURCE_RESOLUTION_AUDIO:
            return download_dir / settings.DOWNLOAD_AUDIO_DIR / self.directory
        else:
            return download_dir / settings.DOWNLOAD_VIDEO_DIR / self.directory

    def make_directory(self):
        return os.makedirs(self.directory_path, exist_ok=True)

    def directory_exists(self):
        return (os.path.isdir(self.directory_path) and
                os.access(self.directory_path, os.W_OK))

    @property
    def key_field(self):
        return self.KEY_FIELD.get(self.source_type, '')

    @property
    def source_resolution_height(self):
        return self.RESOLUTION_MAP.get(self.source_resolution, 0)

    @property
    def can_fallback(self):
        return self.fallback != self.FALLBACK_FAIL

    def index_media(self):
        '''
            Index the media source returning a list of media metadata as dicts.
        '''
        indexer = self.INDEXERS.get(self.source_type, None)
        if not callable(indexer):
            raise Exception(f'Source type f"{self.source_type}" has no indexer')
        response = indexer(self.url)

        # Account for nested playlists, such as a channel of playlists of playlists
        def _recurse_playlists(playlist):
            videos = []
            if not playlist:
                return videos
            entries = playlist.get('entries', [])
            for entry in entries:
                if not entry:
                    continue
                subentries = entry.get('entries', [])
                if subentries:
                    videos = videos + _recurse_playlists(entry)
                else:
                    videos.append(entry)
            return videos

        return _recurse_playlists(response)


def get_media_thumb_path(instance, filename):
    fileid = str(instance.uuid)
    filename = f'{fileid.lower()}.jpg'
    prefix = fileid[:2]
    return Path('thumbs') / prefix / filename


def get_media_file_path(instance, filename):
    return instance.filepath


class Media(models.Model):
    '''
        Media is a single piece of media, such as a single YouTube video linked to a
        Source.
    '''

    # Format to use to display a URL for the media
    URLS = {
        Source.SOURCE_TYPE_YOUTUBE_CHANNEL: 'https://www.youtube.com/watch?v={key}',
        Source.SOURCE_TYPE_YOUTUBE_PLAYLIST: 'https://www.youtube.com/watch?v={key}',
    }
    # Maps standardised names to names used in source metdata
    METADATA_FIELDS = {
        'upload_date': {
            Source.SOURCE_TYPE_YOUTUBE_CHANNEL: 'upload_date',
            Source.SOURCE_TYPE_YOUTUBE_PLAYLIST: 'upload_date',
        },
        'title': {
            Source.SOURCE_TYPE_YOUTUBE_CHANNEL: 'title',
            Source.SOURCE_TYPE_YOUTUBE_PLAYLIST: 'title',
        },
        'thumbnail': {
            Source.SOURCE_TYPE_YOUTUBE_CHANNEL: 'thumbnail',
            Source.SOURCE_TYPE_YOUTUBE_PLAYLIST: 'thumbnail',
        },
        'description': {
            Source.SOURCE_TYPE_YOUTUBE_CHANNEL: 'description',
            Source.SOURCE_TYPE_YOUTUBE_PLAYLIST: 'description',
        },
        'duration': {
            Source.SOURCE_TYPE_YOUTUBE_CHANNEL: 'duration',
            Source.SOURCE_TYPE_YOUTUBE_PLAYLIST: 'duration',
        },
        'formats': {
            Source.SOURCE_TYPE_YOUTUBE_CHANNEL: 'formats',
            Source.SOURCE_TYPE_YOUTUBE_PLAYLIST: 'formats',
        }
    }
    STATE_UNKNOWN = 'unknown'
    STATE_SCHEDULED = 'scheduled'
    STATE_DOWNLOADING = 'downloading'
    STATE_DOWNLOADED = 'downloaded'
    STATE_ERROR = 'error'
    STATES = (STATE_UNKNOWN, STATE_SCHEDULED, STATE_DOWNLOADING, STATE_DOWNLOADED,
              STATE_ERROR)
    STATE_ICONS = {
        STATE_UNKNOWN: '<i class="far fa-question-circle" title="Unknown download state"></i>',
        STATE_SCHEDULED: '<i class="far fa-clock" title="Scheduled to download"></i>',
        STATE_DOWNLOADING: '<i class="fas fa-download" title="Downloading now"></i>',
        STATE_DOWNLOADED: '<i class="far fa-check-circle" title="Downloaded"></i>',
        STATE_ERROR: '<i class="fas fa-exclamation-triangle" title="Error downloading"></i>',
    }

    uuid = models.UUIDField(
        _('uuid'),
        primary_key=True,
        editable=False,
        default=uuid.uuid4,
        help_text=_('UUID of the media')
    )
    created = models.DateTimeField(
        _('created'),
        auto_now_add=True,
        db_index=True,
        help_text=_('Date and time the media was created')
    )
    source = models.ForeignKey(
        Source,
        on_delete=models.CASCADE,
        related_name='media_source',
        help_text=_('Source the media belongs to')
    )
    published = models.DateTimeField(
        _('published'),
        db_index=True,
        null=True,
        blank=True,
        help_text=_('Date and time the media was published on the source')
    )
    key = models.CharField(
        _('key'),
        max_length=100,
        db_index=True,
        help_text=_('Media key, such as exact YouTube video ID')
    )
    thumb = models.ImageField(
        _('thumb'),
        upload_to=get_media_thumb_path,
        max_length=200,
        blank=True,
        null=True,
        width_field='thumb_width',
        height_field='thumb_height',
        help_text=_('Thumbnail')
    )
    thumb_width = models.PositiveSmallIntegerField(
        _('thumb width'),
        blank=True,
        null=True,
        help_text=_('Width (X) of the thumbnail')
    )
    thumb_height = models.PositiveSmallIntegerField(
        _('thumb height'),
        blank=True,
        null=True,
        help_text=_('Height (Y) of the thumbnail')
    )
    metadata = models.TextField(
        _('metadata'),
        blank=True,
        null=True,
        help_text=_('JSON encoded metadata for the media')
    )
    can_download = models.BooleanField(
        _('can download'),
        db_index=True,
        default=False,
        help_text=_('Media has a matching format and can be downloaded')
    )
    media_file = models.FileField(
        _('media file'),
        upload_to=get_media_file_path,
        max_length=200,
        blank=True,
        null=True,
        storage=media_file_storage,
        help_text=_('Media file')
    )
    downloaded = models.BooleanField(
        _('downloaded'),
        db_index=True,
        default=False,
        help_text=_('Media has been downloaded')
    )
    downloaded_audio_codec = models.CharField(
        _('downloaded audio codec'),
        max_length=30,
        db_index=True,
        blank=True,
        null=True,
        help_text=_('Audio codec of the downloaded media')
    )
    downloaded_video_codec = models.CharField(
        _('downloaded video codec'),
        max_length=30,
        db_index=True,
        blank=True,
        null=True,
        help_text=_('Video codec of the downloaded media')
    )
    downloaded_container = models.CharField(
        _('downloaded container format'),
        max_length=30,
        db_index=True,
        blank=True,
        null=True,
        help_text=_('Container format of the downloaded media')
    )
    downloaded_fps = models.PositiveSmallIntegerField(
        _('downloaded fps'),
        db_index=True,
        blank=True,
        null=True,
        help_text=_('FPS of the downloaded media')
    )
    downloaded_hdr = models.BooleanField(
        _('downloaded hdr'),
        default=False,
        help_text=_('Downloaded media has HDR')
    )
    downloaded_filesize = models.PositiveBigIntegerField(
        _('downloaded filesize'),
        db_index=True,
        blank=True,
        null=True,
        help_text=_('Size of the downloaded media in bytes')
    )

    def __str__(self):
        return self.key

    class Meta:
        verbose_name = _('Media')
        verbose_name_plural = _('Media')
        unique_together = (
            ('source', 'key'),
        )

    def get_metadata_field(self, field):
        fields = self.METADATA_FIELDS.get(field, {})
        return fields.get(self.source.source_type, '')

    def iter_formats(self):
        for fmt in self.formats:
            yield parse_media_format(fmt)

    def get_best_combined_format(self):
        return get_best_combined_format(self)

    def get_best_audio_format(self):
        return get_best_audio_format(self)

    def get_best_video_format(self):
        return get_best_video_format(self)

    def get_format_str(self):
        '''
            Returns a youtube-dl compatible format string for the best matches
            combination of source requirements and available audio and video formats.
            Returns boolean False if there is no valid downloadable combo.
        '''
        if self.source.is_audio:
            audio_match, audio_format = self.get_best_audio_format()
            if audio_format:
                return str(audio_format)
            else:
                return False
        else:
            combined_match, combined_format = self.get_best_combined_format()
            if combined_format:
                return str(combined_format)
            else:
                audio_match, audio_format = self.get_best_audio_format()
                video_match, video_format = self.get_best_video_format()
                if audio_format and video_format:
                    return f'{video_format}+{audio_format}'
                else:
                    return False
        return False
    
    def get_format_by_code(self, format_code):
        '''
            Matches a format code, such as '22', to a processed format dict.
        '''
        for fmt in self.iter_formats():
            if format_code == fmt['id']:
                return fmt
        return False

    @property
    def loaded_metadata(self):
        try:
            return json.loads(self.metadata)
        except Exception as e:
            return {}

    @property
    def url(self):
        url = self.URLS.get(self.source.source_type, '')
        return url.format(key=self.key)

    @property
    def description(self):
        field = self.get_metadata_field('description')
        return self.loaded_metadata.get(field, '').strip()

    @property
    def title(self):
        field = self.get_metadata_field('title')
        return self.loaded_metadata.get(field, '').strip()

    @property
    def thumbnail(self):
        field = self.get_metadata_field('thumbnail')
        return self.loaded_metadata.get(field, '').strip()

    @property
    def name(self):
        title = self.title
        return title if title else self.key

    @property
    def upload_date(self):
        field = self.get_metadata_field('upload_date')
        upload_date_str = self.loaded_metadata.get(field, '').strip()
        try:
            return datetime.strptime(upload_date_str, '%Y%m%d')
        except (AttributeError, ValueError) as e:
            return None

    @property
    def duration(self):
        field = self.get_metadata_field('duration')
        return int(self.loaded_metadata.get(field, 0))

    @property
    def duration_formatted(self):
        duration = self.duration
        if duration > 0:
            return seconds_to_timestr(duration)
        return '??:??:??'

    @property
    def formats(self):
        field = self.get_metadata_field('formats')
        return self.loaded_metadata.get(field, [])

    @property
    def filename(self):
        if self.media_file:
            return os.path.basename(self.media_file.name)
        upload_date = self.upload_date
        dateobj = upload_date if upload_date else self.created
        datestr = dateobj.strftime('%Y-%m-%d')
        source_name = slugify(self.source.name).replace('_', '-')
        name = slugify(self.name.replace('&', 'and').replace('+', 'and'))
        name = name.replace('_', '-')[:80]
        key = self.key.strip().replace('_', '-')[:20]
        fmt = []
        if self.source.is_audio:
            fmt.append(self.source.source_acodec.lower())
        else:
            fmt.append(self.source.source_resolution.lower())
            fmt.append(self.source.source_vcodec.lower())
            fmt.append(self.source.source_acodec.lower())
        if self.source.prefer_60fps:
            fmt.append('60fps')
        if self.source.prefer_hdr:
            fmt.append('hdr')
        fmt = '-'.join(fmt)
        ext = self.source.extension
        return f'{datestr}_{source_name}_{name}_{key}_{fmt}.{ext}'

    @property
    def filepath(self):
        return self.source.directory_path / self.filename

    @property
    def thumb_file_exists(self):
        if not self.thumb:
            return False
        return os.path.exists(self.thumb.path)

    @property
    def media_file_exists(self):
        if not self.media_file:
            return False
        return os.path.exists(self.media_file.path)

    def get_download_state(self, task=None):
        if self.downloaded:
            return self.STATE_DOWNLOADED
        if task:
            if task.locked_by_pid_running():
                return self.STATE_DOWNLOADING
            elif task.has_error():
                return self.STATE_ERROR
            else:
                return self.STATE_SCHEDULED
        return self.STATE_UNKNOWN

    def get_download_state_icon(self, task=None):
        state = self.get_download_state(task)
        return self.STATE_ICONS.get(state, self.STATE_ICONS[self.STATE_UNKNOWN])

    def download_media(self):
        format_str = self.get_format_str()
        if not format_str:
            raise NoFormatException(f'Cannot download, media "{self.pk}" ({media}) has '
                                    f'no valid format available')
        # Download the media with youtube-dl
        download_youtube_media(self.url, format_str, self.source.extension,
                               str(self.filepath))
        # Return the download paramaters
        return format_str, self.source.extension