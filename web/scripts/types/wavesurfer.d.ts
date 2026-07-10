// Minimal, honest ambient typings for the vendored wavesurfer.js v7 ESM bundles.
// Only the subset of the API used by the trim editor is declared here.
// Full API: https://wavesurfer.xyz/docs/

declare module "wavesurfer" {
  export interface WaveSurferOptions {
    container: HTMLElement;
    url?: string;
    /** "WebAudio" = sample-accurate playback from the decoded buffer. */
    backend?: "WebAudio" | "MediaElement";
    height?: number | "auto";
    waveColor?: string;
    progressColor?: string;
    cursorColor?: string;
    cursorWidth?: number;
    barWidth?: number;
    barGap?: number;
    barRadius?: number;
    minPxPerSec?: number;
    fillParent?: boolean;
    autoScroll?: boolean;
    autoCenter?: boolean;
    normalize?: boolean;
    interact?: boolean;
    dragToSeek?: boolean;
    mediaControls?: boolean;
    hideScrollbar?: boolean;
    plugins?: GenericPlugin[];
  }

  // Opaque plugin handle — concrete plugins declare their own module.
  export interface GenericPlugin {
    destroy(): void;
  }

  export type WaveSurferEvent =
    | "load"
    | "loading"
    | "decode"
    | "ready"
    | "play"
    | "pause"
    | "finish"
    | "timeupdate"
    | "audioprocess"
    | "seeking"
    | "interaction"
    | "click"
    | "destroy"
    | "error";

  export default class WaveSurfer {
    static create(options: WaveSurferOptions): WaveSurfer;
    registerPlugin<T extends GenericPlugin>(plugin: T): T;
    load(url: string): Promise<void>;
    on(event: "ready", cb: (duration: number) => void): () => void;
    on(event: "timeupdate", cb: (currentTime: number) => void): () => void;
    on(event: "audioprocess", cb: (currentTime: number) => void): () => void;
    on(event: "error", cb: (err: Error) => void): () => void;
    on(event: WaveSurferEvent, cb: (...args: unknown[]) => void): () => void;
    un(event: WaveSurferEvent, cb: (...args: unknown[]) => void): void;
    play(): Promise<void>;
    pause(): void;
    playPause(): Promise<void>;
    stop(): void;
    isPlaying(): boolean;
    setTime(seconds: number): void;
    getCurrentTime(): number;
    getDuration(): number;
    setVolume(volume: number): void;
    getVolume(): number;
    zoom(minPxPerSec: number): void;
    getDecodedData(): AudioBuffer | null;
    setOptions(options: Partial<WaveSurferOptions>): void;
    empty(): void;
    destroy(): void;
  }
}

declare module "wavesurfer-regions" {
  import { GenericPlugin } from "wavesurfer";

  export interface RegionParams {
    id?: string;
    start: number;
    end?: number;
    drag?: boolean;
    resize?: boolean;
    color?: string;
    content?: string | HTMLElement;
    minLength?: number;
    maxLength?: number;
  }

  export interface Region {
    id: string;
    start: number;
    end: number;
    setOptions(options: Partial<RegionParams>): void;
    play(): void;
    remove(): void;
    on(event: "update", cb: (side?: "start" | "end") => void): () => void;
    on(event: "update-end", cb: () => void): () => void;
    on(event: "remove", cb: () => void): () => void;
  }

  export type RegionsEvent =
    | "region-created"
    | "region-updated"
    | "region-update"
    | "region-in"
    | "region-out"
    | "region-clicked"
    | "region-removed";

  export default class RegionsPlugin implements GenericPlugin {
    static create(): RegionsPlugin;
    addRegion(params: RegionParams): Region;
    getRegions(): Region[];
    clearRegions(): void;
    on(event: "region-updated", cb: (region: Region) => void): () => void;
    on(event: "region-update", cb: (region: Region) => void): () => void;
    on(event: "region-out", cb: (region: Region) => void): () => void;
    on(event: RegionsEvent, cb: (...args: unknown[]) => void): () => void;
    destroy(): void;
  }
}
