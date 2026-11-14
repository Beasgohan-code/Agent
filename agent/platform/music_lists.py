"""Bounded, explicitly saved Music metadata, isolated by bot/group/user."""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urlsplit

from .net import parse_url, check_target

SCHEMA = ("""CREATE TABLE IF NOT EXISTS agent_music_playlists (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK (group_id < 0),
    owner_id BIGINT NOT NULL CHECK (owner_id > 0),
    name TEXT NOT NULL CHECK (name ~ '^[a-z0-9_-]{1,32}$'),
    tracks JSONB NOT NULL CHECK (jsonb_typeof(tracks) = 'array'
        AND jsonb_array_length(tracks) BETWEEN 1 AND 20),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant, group_id, owner_id, name))""",)


class PlaylistError(RuntimeError):
    pass


async def validate_tracks(tracks):
    """Reject local paths/credentials; DNS is rechecked on save and every load.

    This is admission validation, not a pinned HTTP proxy: native streaming
    retains the existing redirect/DNS-rebinding limitations documented for Music.
    """
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= 20:
        raise PlaylistError('A playlist must contain between 1 and 20 tracks.')
    clean = []
    for track in tracks:
        if not isinstance(track, dict) or not isinstance(track.get('source'), str):
            raise PlaylistError('This playlist contains invalid track metadata.')
        try:
            source = parse_url(track['source'])
            parts = urlsplit(source)
            _ = parts.port  # force validation of malformed numeric ports
            if (len(source) > 2048 or parts.query or parts.fragment
                    or any(ord(char) <= 32 or ord(char) == 127 for char in source)):
                raise ValueError('not a stable URL')
        except ValueError:
            raise PlaylistError('Save only stable public HTTP(S) media URLs, without credentials, query strings or fragments. Local Telegram downloads cannot be saved.') from None
        # LinkError is a RuntimeError; never expose a URL in exception text.
        except RuntimeError:
            raise PlaylistError('Save only public HTTP(S) media URLs; local files and credentials are not supported.') from None
        title = track.get('title')
        if not isinstance(title, str) or not title.strip():
            raise PlaylistError('A track title is missing.')
        clean.append({'source': source, 'title': title[:160]})
    try:
        results = await asyncio.wait_for(asyncio.gather(*(check_target(item['source']) for item in clean), return_exceptions=True), timeout=8)
        if any(isinstance(result, BaseException) for result in results):
            raise ValueError('address validation failed')
    except Exception:
        raise PlaylistError('A saved media address could not be validated as public. No tracks were loaded.') from None
    return clean


class MusicPlaylists:
    def __init__(self, db):
        self.db = db

    def _scope(self, group_id, owner_id, name=None):
        if (self.db is None or not self.db.connected or self.db._pool is None):
            raise PlaylistError('PostgreSQL is unavailable; no playlist operation was performed.')
        if (not isinstance(group_id, int) or isinstance(group_id, bool) or group_id >= 0
                or not isinstance(owner_id, int) or isinstance(owner_id, bool) or owner_id <= 0):
            raise PlaylistError('A group and authenticated user are required.')
        if name is not None and (not isinstance(name, str) or re.fullmatch('[a-z0-9_-]{1,32}', name) is None):
            raise PlaylistError('Use a name of 1–32 lowercase letters, numbers, underscores or hyphens.')
        return self.db.scope, group_id, owner_id

    async def save(self, group_id, owner_id, name, tracks):
        scope = self._scope(group_id, owner_id, name)
        tracks = await validate_tracks(tracks)
        async with self.db._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))',
                                   'agent:music:playlists:' + json.dumps(scope))
                exists = await conn.fetchval('SELECT 1 FROM agent_music_playlists WHERE tenant=$1 AND group_id=$2 AND owner_id=$3 AND name=$4', *scope, name)
                count = await conn.fetchval('SELECT count(*) FROM agent_music_playlists WHERE tenant=$1 AND group_id=$2 AND owner_id=$3', *scope)
                if not exists and count >= 10:
                    raise PlaylistError('You already have 10 playlists in this group. Delete one first.')
                await conn.execute('''INSERT INTO agent_music_playlists (tenant,group_id,owner_id,name,tracks)
                    VALUES ($1,$2,$3,$4,$5::jsonb)
                    ON CONFLICT (tenant,group_id,owner_id,name)
                    DO UPDATE SET tracks=EXCLUDED.tracks,updated_at=now()''', *scope, name, json.dumps(tracks))
        return len(tracks)

    async def list(self, group_id, owner_id):
        scope = self._scope(group_id, owner_id)
        async with self.db._pool.acquire() as conn:
            return await conn.fetch('''SELECT name,jsonb_array_length(tracks) AS count FROM agent_music_playlists
                WHERE tenant=$1 AND group_id=$2 AND owner_id=$3 ORDER BY name LIMIT 10''', *scope)

    async def load(self, group_id, owner_id, name):
        scope = self._scope(group_id, owner_id, name)
        async with self.db._pool.acquire() as conn:
            value = await conn.fetchval('SELECT tracks FROM agent_music_playlists WHERE tenant=$1 AND group_id=$2 AND owner_id=$3 AND name=$4', *scope, name)
        if value is None:
            raise PlaylistError('No playlist with that name belongs to you in this group.')
        try:
            tracks = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError):
            raise PlaylistError('Saved playlist metadata could not be read.') from None
        return await validate_tracks(tracks)

    async def delete(self, group_id, owner_id, name):
        scope = self._scope(group_id, owner_id, name)
        async with self.db._pool.acquire() as conn:
            result = await conn.execute('DELETE FROM agent_music_playlists WHERE tenant=$1 AND group_id=$2 AND owner_id=$3 AND name=$4', *scope, name)
        return result == 'DELETE 1'
