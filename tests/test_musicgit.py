"""End-to-end tests for musicgit, using tests/fake-ytdlp instead of the network.

Run with:  python3 -m unittest discover -s tests -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MUSICGIT = ROOT / "musicgit"
FAKE = ROOT / "tests" / "fake-ytdlp"


def track(vid, title, artist="Artist", duration=200):
    return {"id": vid, "title": title, "artist": artist, "duration": duration,
            "url": f"https://music.youtube.com/watch?v={vid}"}


class MusicgitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="musicgit-test-"))
        self.repo = self.tmp / "library"
        self.playlist_file = self.tmp / "playlist.json"
        self.search_file = self.tmp / "search.json"
        self.search_file.write_text(json.dumps({"_type": "playlist", "entries": [
            {"id": "zzzzzzzzzzz", "title": "Song A", "channel": "Artist - Topic",
             "duration": 200},
            {"id": "yyyyyyyyyyy", "title": "Song A (slowed reverb)", "channel": "fan",
             "duration": 200},
        ]}))
        self.set_playlist("Test List", [track("aaaaaaaaaaa", "Song A"),
                                        track("bbbbbbbbbbb", "Song B")])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ---------------------------------------------------------- #
    def set_playlist(self, title, entries, playlist_id="PLtest"):
        self.playlist_file.write_text(json.dumps({
            "_type": "playlist", "id": playlist_id, "title": title,
            "uploader": "Someone", "entries": entries,
        }), encoding="utf-8")

    def run_cli(self, *args, expect=0, env_extra=None):
        env = {
            **os.environ,
            "MUSICGIT_YTDLP": str(FAKE),
            "FAKE_PLAYLIST": str(self.playlist_file),
            "FAKE_SEARCH_JSON": str(self.search_file),
            "FAKE_FAIL": "",
            "FAKE_CERT_ERROR": "0",
        }
        env.update(env_extra or {})
        proc = subprocess.run([sys.executable, str(MUSICGIT), *args],
                              cwd=self.tmp, capture_output=True, text=True, env=env)
        if expect is not None:
            self.assertEqual(proc.returncode, expect,
                             f"exit {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
        return proc

    def init_with_remote(self):
        self.run_cli("init", str(self.repo))
        self.run_cli("-C", str(self.repo), "remote", "add", "faves",
                     "https://music.youtube.com/playlist?list=PLtest")

    def folder(self):
        """Folder musicgit chose for the remote (the playlist title)."""
        snap = json.loads((self.repo / ".musicgit" / "snapshots" / "faves.json").read_text())
        return self.repo / snap["dir"]

    def audio_files(self):
        return sorted(p.name for p in self.folder().glob("*")
                      if p.is_file() and p.suffix == ".opus")

    # -- tests ------------------------------------------------------------ #
    def test_init_creates_state(self):
        self.run_cli("init", str(self.repo))
        self.assertTrue((self.repo / ".musicgit" / "config.json").is_file())
        self.assertTrue((self.repo / ".musicgit" / "snapshots").is_dir())

    def test_status_before_fetch_says_never_fetched(self):
        self.init_with_remote()
        out = self.run_cli("-C", str(self.repo), "status").stdout
        self.assertIn("never fetched", out)

    def test_fetch_then_status_lists_new_tracks(self):
        self.init_with_remote()
        out = self.run_cli("-C", str(self.repo), "fetch", expect=0).stdout
        self.assertIn("2 tracks", out)
        status = self.run_cli("-C", str(self.repo), "status").stdout
        self.assertIn("+ new", status)
        self.assertIn("Song A", status)
        self.assertIn("2 to download", status)
        self.assertFalse(list((self.repo / "faves").glob("*.opus")), "status must not download")

    def test_pull_downloads_named_with_id(self):
        self.init_with_remote()
        self.run_cli("-C", str(self.repo), "pull", expect=0)
        names = self.audio_files()
        self.assertEqual(len(names), 2)
        self.assertTrue(names[0].startswith("001 - Artist - Song A [aaaaaaaaaaa]"))
        self.assertTrue(names[1].startswith("002 - Artist - Song B [bbbbbbbbbbb]"))
        self.assertEqual(self.folder().name, "Test List")
        m3u = (self.folder() / "playlist.m3u8").read_text()
        self.assertIn("Song B", m3u)
        self.assertEqual(m3u.splitlines()[0], "#EXTM3U")

    def test_second_pull_is_a_no_op(self):
        self.init_with_remote()
        self.run_cli("-C", str(self.repo), "pull", expect=0)
        before = self.audio_files()
        proc = self.run_cli("-C", str(self.repo), "pull", expect=0)
        self.assertIn("0 to download", proc.stdout)
        self.assertEqual(self.audio_files(), before)
        status = self.run_cli("-C", str(self.repo), "status").stdout
        self.assertIn("up to date", status)

    def test_parallel_downloads(self):
        self.set_playlist("Test List", [track(f"{c}aaaaaaaaaa", f"Song {c}") for c in "defg"])
        self.init_with_remote()
        self.run_cli("-C", str(self.repo), "pull", "-j", "4", expect=0)
        self.assertEqual(len(self.audio_files()), 4)
        self.assertEqual(len(self.audio_files()), len(set(self.audio_files())))

    def test_playlist_update_downloads_only_the_delta(self):
        self.init_with_remote()
        self.run_cli("-C", str(self.repo), "pull", expect=0)
        self.set_playlist("Test List", [track("aaaaaaaaaaa", "Song A"),
                                        track("bbbbbbbbbbb", "Song B"),
                                        track("ccccccccccc", "Song C", artist="Other")])
        self.run_cli("-C", str(self.repo), "fetch", expect=0)
        status = self.run_cli("-C", str(self.repo), "status").stdout
        self.assertIn("1 to download", status)
        self.assertIn("Song C", status)
        proc = self.run_cli("-C", str(self.repo), "pull", expect=0)
        self.assertIn("1 downloaded", proc.stdout)
        self.assertEqual(len(self.audio_files()), 3)

    def test_removed_track_is_reported_and_pruned_on_request(self):
        self.init_with_remote()
        self.run_cli("-C", str(self.repo), "pull", expect=0)
        self.set_playlist("Test List", [track("aaaaaaaaaaa", "Song A")])
        self.run_cli("-C", str(self.repo), "fetch", expect=0)
        status = self.run_cli("-C", str(self.repo), "status").stdout
        self.assertIn("gone upstream", status)

        # without --prune the file stays
        self.run_cli("-C", str(self.repo), "pull", expect=0)
        self.assertEqual(len(self.audio_files()), 2)

        self.run_cli("-C", str(self.repo), "pull", "--prune", expect=0)
        self.assertEqual(len(self.audio_files()), 1)
        removed = list((self.repo / ".musicgit" / "removed" / "faves").glob("*"))
        self.assertEqual(len(removed), 1)

    def test_failure_is_recorded_listed_and_retried(self):
        self.init_with_remote()
        proc = self.run_cli("-C", str(self.repo), "pull", expect=1,
                            env_extra={"FAKE_FAIL": "bbbbbbbbbbb"})
        self.assertIn("FAILED", proc.stdout)
        self.assertEqual(len(self.audio_files()), 1)

        failed = self.run_cli("-C", str(self.repo), "failed", expect=1).stdout
        self.assertIn("Song B", failed)
        self.assertIn("Video unavailable", failed)

        data = json.loads((self.repo / ".musicgit" / "failures.json").read_text())
        self.assertIn("bbbbbbbbbbb", data["faves"])
        self.assertTrue((self.repo / ".musicgit" / "failures.md").is_file())

        # retry while still broken keeps the record
        self.run_cli("-C", str(self.repo), "retry", expect=1,
                     env_extra={"FAKE_FAIL": "bbbbbbbbbbb"})
        data = json.loads((self.repo / ".musicgit" / "failures.json").read_text())
        self.assertIn("bbbbbbbbbbb", data["faves"])

        # retry once the track works again
        self.run_cli("-C", str(self.repo), "retry", expect=0)
        self.assertEqual(len(self.audio_files()), 2)
        data = json.loads((self.repo / ".musicgit" / "failures.json").read_text())
        self.assertNotIn("faves", data)
        self.run_cli("-C", str(self.repo), "failed", expect=0)

    def test_finished_audio_is_kept_when_postprocessing_fails(self):
        self.init_with_remote()
        self.run_cli("-C", str(self.repo), "pull", "-j", "2", expect=0,
                     env_extra={"FAKE_POSTPROCESS_ERROR": "1"})
        self.assertEqual(len(self.audio_files()), 2)
        data = json.loads((self.repo / ".musicgit" / "failures.json").read_text())
        self.assertNotIn("faves", data)

    def test_retry_search_substitutes_alternate_upload(self):
        self.init_with_remote()
        self.run_cli("-C", str(self.repo), "pull", expect=1,
                     env_extra={"FAKE_FAIL": "aaaaaaaaaaa"})
        proc = self.run_cli("-C", str(self.repo), "retry", "--search", "-j", "1",
                            expect=0, env_extra={"FAKE_FAIL": "aaaaaaaaaaa"})
        self.assertIn("alternate upload", proc.stdout)
        # file keeps the playlist's original id, so the entry now counts as done
        self.assertTrue(any("[aaaaaaaaaaa]" in n and "Song A" in n
                            for n in self.audio_files()))
        subs = json.loads((self.repo / ".musicgit" / "substitutions.json").read_text())
        self.assertEqual(subs["faves"]["aaaaaaaaaaa"]["source_id"], "zzzzzzzzzzz")
        self.assertNotIn("faves", json.loads(
            (self.repo / ".musicgit" / "failures.json").read_text()))

    def test_retry_only_limits_to_given_ids(self):
        self.set_playlist("Test List", [track("aaaaaaaaaaa", "Song A"),
                                        track("bbbbbbbbbbb", "Song B"),
                                        track("ccccccccccc", "Song C")])
        self.init_with_remote()
        self.run_cli("-C", str(self.repo), "pull", expect=1,
                     env_extra={"FAKE_FAIL": "aaaaaaaaaaa,bbbbbbbbbbb"})
        self.run_cli("-C", str(self.repo), "retry", "--only", "bbbbbbbbbbb", expect=0)
        names = self.audio_files()
        self.assertTrue(any("[bbbbbbbbbbb]" in n for n in names))
        self.assertFalse(any("[aaaaaaaaaaa]" in n for n in names))

    def test_retry_only_keeps_the_other_failures(self):
        self.set_playlist("Test List", [track("aaaaaaaaaaa", "Song A"),
                                        track("bbbbbbbbbbb", "Song B")])
        self.init_with_remote()
        self.run_cli("-C", str(self.repo), "pull", expect=1,
                     env_extra={"FAKE_FAIL": "aaaaaaaaaaa,bbbbbbbbbbb"})
        self.run_cli("-C", str(self.repo), "retry", "--only", "bbbbbbbbbbb", expect=0)
        data = json.loads((self.repo / ".musicgit" / "failures.json").read_text())
        self.assertEqual(sorted(data["faves"]), ["aaaaaaaaaaa"])

    def test_topic_suffix_is_stripped_when_fetching(self):
        self.set_playlist("Test List", [{"id": "aaaaaaaaaaa", "title": "Song A",
                                        "artist": "Someone - Topic", "duration": 200,
                                        "url": "https://music.youtube.com/watch?v=aaaaaaaaaaa"}])
        self.init_with_remote()
        self.run_cli("-C", str(self.repo), "fetch", expect=0)
        snap = json.loads((self.repo / ".musicgit" / "snapshots" / "faves.json").read_text())
        self.assertEqual(snap["tracks"][0]["artist"], "Someone")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg needed to build a test file")
    def test_retag_strips_topic_suffix_on_disk(self):
        try:
            from mutagen import File as MutagenFile  # noqa: PLC0415
        except ImportError:
            self.skipTest("mutagen not installed")
        self.init_with_remote()
        self.run_cli("-C", str(self.repo), "fetch", expect=0)
        folder = self.folder()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "001 - Artist - Song A [aaaaaaaaaaa].opus"
        subprocess.run([
            "ffmpeg", "-v", "quiet", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "libopus", "-metadata", "artist=Artist - Topic",
            "-metadata", "title=Song A", str(path),
        ], check=True)
        self.run_cli("-C", str(self.repo), "retag", expect=0)
        audio = MutagenFile(str(path), easy=True)
        self.assertEqual(audio["artist"][0], "Artist")
        self.assertEqual(audio["albumartist"][0], "Artist")

    def test_tls_error_is_explained(self):
        self.init_with_remote()
        proc = self.run_cli("-C", str(self.repo), "pull", expect=1,
                            env_extra={"FAKE_CERT_ERROR": "1"})
        self.assertIn("certificate", proc.stderr.lower())
        self.assertIn("content filter", proc.stderr.lower())

    def test_log_records_pulls(self):
        self.init_with_remote()
        self.run_cli("-C", str(self.repo), "pull", expect=0)
        out = self.run_cli("-C", str(self.repo), "log").stdout
        self.assertIn("pull", out)
        self.assertIn("+2 new", out)

    def test_remote_list_and_remove(self):
        self.init_with_remote()
        self.assertIn("faves", self.run_cli("-C", str(self.repo), "remote", "list").stdout)
        self.run_cli("-C", str(self.repo), "remote", "remove", "faves", expect=0)
        out = self.run_cli("-C", str(self.repo), "remote", "list").stdout
        self.assertIn("no remotes", out)

    def test_bare_playlist_id_is_expanded(self):
        self.run_cli("init", str(self.repo))
        out = self.run_cli("-C", str(self.repo), "remote", "add", "raw",
                           "PLdQw4w9WgXcQabc").stdout
        self.assertIn("music.youtube.com/playlist?list=PLdQw4w9WgXcQabc", out)

    def test_not_a_repo_is_a_clear_error(self):
        proc = self.run_cli("status", expect=1)
        self.assertIn("not a musicgit repo", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
