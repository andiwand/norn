// Picks the stream quality a connection can carry: steps down when playback struggles, and
// tries one step up again after a long calm, waiting longer after each failed try.
//
// It only looks at the <video> element, so it works for WebRTC and MSE alike: stalls (the
// `waiting` event), dropped frames, and time that doesn't move while the video should play.

export interface Health {
	/** `waiting` events since the last check. */
	stalls: number;
	/** Frames decoded and dropped since the last check. */
	frames: number;
	dropped: number;
	/** The video's time didn't move although it should play. */
	frozen: boolean;
}

export const CHECK_MS = 2000;
const STRIKES = 3; // bad checks in a row before stepping down
const SETTLE_MS = 10_000; // a new stream stalls while it starts; that says nothing yet
const CALM_MS = 120_000; // calm before trying one step up
const MAX_WAIT_MS = 30 * 60_000;

export class QualityGuard {
	/** Index into the ladder: 0 is the best quality. */
	level = 0;
	#strikes = 0;
	#calmSince: number;
	#upWait = CALM_MS;
	#triedUpAt: number | null = null;
	#since: number; // when the current stream started
	#frozen = 0; // checks in a row with a frozen picture

	constructor(
		readonly ladder: string[],
		start = 0,
		now = Date.now()
	) {
		this.level = Math.min(start, ladder.length - 1);
		this.#calmSince = now;
		this.#since = now;
	}

	get stream(): string {
		return this.ladder[this.level];
	}

	static bad(h: Health): boolean {
		return h.stalls > 0 || h.frozen || (h.frames >= 10 && h.dropped / h.frames > 0.2);
	}

	/** Feed one check; the stream to play now (a change means: switch to it). */
	check(health: Health, now = Date.now()): string {
		if (now - this.#since < SETTLE_MS) return this.stream;
		// A picture that doesn't move for one check can be a slow keyframe; two is a freeze.
		this.#frozen = health.frozen ? this.#frozen + 1 : 0;
		const bad = QualityGuard.bad({ ...health, frozen: this.#frozen >= 2 });
		if (bad) {
			this.#strikes++;
			this.#calmSince = now;
			if (this.#strikes >= STRIKES) this.down(now);
		} else {
			this.#strikes = 0;
			if (this.#triedUpAt !== null && now - this.#triedUpAt > 30_000) {
				this.#triedUpAt = null; // the step up held
				this.#upWait = CALM_MS;
			}
			if (this.level > 0 && now - this.#calmSince >= this.#upWait) {
				this.level--;
				this.#triedUpAt = now;
				this.#calmSince = now;
				this.#since = now;
			}
		}
		return this.stream;
	}

	/** Playback failed outright (or struggled long enough): one step down, if there is one. */
	down(now = Date.now()): string {
		this.#strikes = 0;
		this.#calmSince = now;
		if (this.#triedUpAt !== null) {
			// The step up didn't hold: wait longer before the next try.
			this.#upWait = Math.min(this.#upWait * 2, MAX_WAIT_MS);
			this.#triedUpAt = null;
		}
		if (this.level < this.ladder.length - 1) {
			this.level++;
			this.#since = now;
		}
		return this.stream;
	}
}

/** Watch a <video>: call `report` with its health every CHECK_MS. Returns a stop function. */
export function watchVideo(video: HTMLVideoElement, report: (h: Health) => void): () => void {
	let stalls = 0;
	let lastTime = video.currentTime;
	let lastQuality = video.getVideoPlaybackQuality?.();
	const onWaiting = () => stalls++;
	video.addEventListener('waiting', onWaiting);
	const timer = setInterval(() => {
		const quality = video.getVideoPlaybackQuality?.();
		const frames =
			quality && lastQuality ? quality.totalVideoFrames - lastQuality.totalVideoFrames : 0;
		const dropped =
			quality && lastQuality ? quality.droppedVideoFrames - lastQuality.droppedVideoFrames : 0;
		const playing = !video.paused && video.readyState >= 2 && !document.hidden;
		const frozen = playing && video.currentTime === lastTime;
		report({ stalls, frames, dropped, frozen });
		stalls = 0;
		lastTime = video.currentTime;
		lastQuality = quality;
	}, CHECK_MS);
	return () => {
		clearInterval(timer);
		video.removeEventListener('waiting', onWaiting);
	};
}
