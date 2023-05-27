#!/bin/sh
hypercorn app.web.app:app --bind '[::]:8080' --reload