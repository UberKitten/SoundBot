import { deleteSync } from "del";
import gulp from "gulp";
import rev from "gulp-rev";
import path from "node:path";
import ts from "gulp-typescript";
import tsconfig from "./tsconfig.json" assert { type: "json" };
const { src, dest, series, parallel } = gulp;

const staticPath = "./static";

function cleanStyles(cb) {
  deleteSync([path.resolve(staticPath, "styles/**/*-*.css")]);
  cb();
}

function buildStyles() {
  return src(path.resolve(staticPath, "src/styles/**/*.css"))
    .pipe(rev())
    .pipe(dest(path.resolve(staticPath, "styles")));
}

function cleanScripts(cb) {
  deleteSync([path.resolve(staticPath, "scripts/**/*-*.js")]);
  cb();
}

function buildScripts() {
  return src(path.resolve(staticPath, "src/scripts/**/*.ts"))
    .pipe(ts(tsconfig.compilerOptions))
    .pipe(rev())
    .pipe(dest(path.resolve(staticPath, "scripts")));
}

const defaultTask = parallel(
  series(cleanStyles, buildStyles),
  series(cleanScripts, buildScripts)
);

function watchStyles() {
  return gulp.watch(
    path.resolve(staticPath, "src/styles/**/*.css"),
    series(cleanStyles, buildStyles)
  );
}

function watchScripts() {
  return gulp.watch(
    path.resolve(staticPath, "src/scripts/**/*.ts"),
    series(cleanScripts, buildScripts)
  );
}

export const watch = series(defaultTask, parallel(watchStyles, watchScripts));
export default defaultTask;
