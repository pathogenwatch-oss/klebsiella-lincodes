# plincer - Pathogenwatch LIN code assigner

## About
This program takes in the output from the cgMLST code (run against the Pasteur/`klebsiella_1` scheme) and assigns the nearest LIN code.

## To build
This will pull a fresh copy of the database from the Pasteur.
```
docker build --rm --pull --build-arg VERSION=5.0.1 -t registry.gitlab.com/cgps/pathogenwatch/analyses/plicer:v5.0.1 .
```
