import { shouldUseMediaElementEngine } from "audio-platform";
import type { AudioPlatformNavigator } from "audio-platform";

export type WaveformPlaybackBackend = "WebAudio" | "MediaElement";

interface WaveformPlayer {
  getMediaElement(): HTMLMediaElement;
  play(): Promise<void>;
  setVolume(volume: number): void;
}

interface MediaElementBridge {
  context: AudioContext;
  source: MediaElementAudioSourceNode;
  gain: GainNode;
}

export interface WaveformPreviewPlayback {
  readonly backend: WaveformPlaybackBackend;
  setVolume(volume: number): void;
  play(): Promise<void>;
  destroy(): void;
}

export function selectWaveformPlaybackBackend(
  nav?: AudioPlatformNavigator
): WaveformPlaybackBackend {
  return shouldUseMediaElementEngine(nav) ? "MediaElement" : "WebAudio";
}

function unlockAudioContext(context: AudioContext | undefined): Promise<void> {
  if (!context || context.state === "running") return Promise.resolve();
  if (context.state === "closed") {
    return Promise.reject(new Error("Preview AudioContext is closed"));
  }
  return context.resume().then(() => {
    if (context.state !== "running") {
      throw new Error("Preview AudioContext did not enter the running state");
    }
  });
}

class PreviewPlayback implements WaveformPreviewPlayback {
  private bridge: MediaElementBridge | null = null;
  private volume = 1;
  private destroyed = false;

  constructor(
    private readonly player: WaveformPlayer,
    readonly backend: WaveformPlaybackBackend,
    volume: number
  ) {
    this.volume = Math.max(0, volume);
    this.applyVolume();
  }

  setVolume(volume: number): void {
    if (this.destroyed) return;
    this.volume = Math.max(0, volume);
    this.applyVolume();
  }

  async play(): Promise<void> {
    if (this.destroyed) throw new Error("Preview playback is destroyed");

    const context =
      this.backend === "MediaElement"
        ? this.ensureMediaElementBridge().context
        : this.webAudioContext();
    const contextReady = unlockAudioContext(context);
    const mediaStarted = this.player.play();
    await Promise.all([contextReady, mediaStarted]);
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;

    const bridge = this.bridge;
    this.bridge = null;
    if (!bridge) return;

    bridge.source.disconnect();
    bridge.gain.disconnect();
    void bridge.context.close().catch(() => {});
  }

  private applyVolume(): void {
    if (this.backend === "WebAudio") {
      this.player.setVolume(this.volume);
      return;
    }

    if (!this.bridge) {
      // Native media volume is limited to 0..1. The lazy GainNode bridge takes
      // over on first play and preserves the editor's existing 0..200% range.
      this.player.setVolume(Math.min(this.volume, 1));
      return;
    }

    this.player.setVolume(1);
    this.bridge.gain.gain.value = this.volume;
  }

  private ensureMediaElementBridge(): MediaElementBridge {
    if (this.bridge) return this.bridge;

    const context = new AudioContext();
    try {
      const source = context.createMediaElementSource(
        this.player.getMediaElement()
      );
      const gain = context.createGain();
      source.connect(gain);
      gain.connect(context.destination);
      this.bridge = { context, source, gain };
      this.applyVolume();
      return this.bridge;
    } catch (error) {
      void context.close().catch(() => {});
      throw error;
    }
  }

  private webAudioContext(): AudioContext | undefined {
    const media = this.player.getMediaElement() as HTMLMediaElement & {
      audioContext?: AudioContext;
    };
    return media.audioContext;
  }
}

export function createWaveformPreviewPlayback(
  player: WaveformPlayer,
  backend: WaveformPlaybackBackend,
  volume: number
): WaveformPreviewPlayback {
  return new PreviewPlayback(player, backend, volume);
}
