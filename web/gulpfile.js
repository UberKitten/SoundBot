import { deleteSync } from "del";
import gulp from "gulp";
import rev from "gulp-rev";
import path from "node:path";
import ts from "gulp-typescript";
import tsconfig from "./tsconfig.json" assert { type: "json" };
const { src, dest, series, parallel } = gulp;

const sourcePath = "./";
const distPath = "./dist";

function cleanDist(cb) {
  deleteSync([path.resolve(distPath, "**/*")]);
  cb();
}

function copyStatic() {
  return src(path.resolve(sourcePath, "static/**/*")).pipe(
    dest(path.resolve(distPath))
  );
}

function buildStyles() {
  return src(path.resolve(sourcePath, "styles/**/*.css"))
    .pipe(rev())
    .pipe(dest(path.resolve(distPath, "styles")));
}

function buildScripts() {
  return src(path.resolve(sourcePath, "scripts/**/*.ts"))
    .pipe(ts(tsconfig.compilerOptions))
    .pipe(rev())
    .pipe(dest(path.resolve(distPath, "scripts")));
}

const buildTask = parallel(buildScripts, buildStyles, copyStatic);
const defaultTask = series(cleanDist, buildTask);

function watchStyles() {
  return gulp.watch(path.resolve(sourcePath, "styles/**/*.css"), buildStyles);
}

function watchScripts() {
  return gulp.watch(path.resolve(sourcePath, "scripts/**/*.ts"), buildScripts);
}

export const watch = series(defaultTask, parallel(watchStyles, watchScripts));
export default defaultTask;
