#!/bin/sh
hypercorn app.web.app:app -b localhost:8080 --reload