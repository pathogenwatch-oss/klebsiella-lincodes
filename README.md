# plincer - Pathogenwatch LIN code assigner

## About

This program takes in the output from the cgMLST code (run against the Pasteur/`klebsiella_1` scheme) and assigns the
nearest LIN code.

## Quick start

### Authentication

You will need to create a user account at the Pasteur and get a consumer key and token first. These will need to go into
a file called `secrets.json`. The format is detailed [below](#secretsjson).

### With Docker (recommended)

#### Building

Make a directory called `cache_dir` in the repository and then run the docker command below. This will pull a fresh copy
of the database from the Pasteur. Note that the BUILD_DATE build argument is used to force Docker to rebuild the
database if the date has changed. Any string could be used and a random string will force a full rebuild.

```
%> docker build --progress plain \
                --build-arg BUILD_DATE=$(date +%Y-%m-%d) \
                --build-arg VERSION=5.0.2 \
                --build-arg LOG=INFO \
                --secret id=secrets,src="$PWD/secrets.json" \
                --cache-from type=local,src=cache_dir \
                --cache-to type=local,dest=cache_dir \
                -t registry.gitlab.com/cgps/pathogenwatch/analyses/plincer:v5.0.2 .
```

#### Running

```
cat my_cgmlst.json | docker run --rm -i registry.gitlab.com/cgps/pathogenwatch/analyses/plincer:v5.0.2 > lincode.json
```

### uv

`plincer` can either be run directly using `uv`, installed as a python package using into `uv` or using `pip` and the
[requirements.txt](./requirements.txt) file.

```
%> uv run plincer --help
```

### secrets.json

The `secrets.json` file contains initial credentials and keys for accessing various MLST databases. It should include:

- User credentials for each host (e.g., PubMLST, Pasteur)
- Consumer keys for each host
- Any initial access or session keys (optional)

Example structure:

```
{
  "pubmlst": {
    "user": {
      "TOKEN": "your_username",
      "TOKEN SECRET": "your_password"
    },
    "consumer": {
      "TOKEN": "your_consumer_key",
      "TOKEN SECRET": "your_consumer_secret"
    }
  }
}
```

#### Mounting the secrets at build time

Using this approach ensures that keys are not stored in the image. It will create a `cache_dir` directory

- `id=secrets,src="path/to/secrets.json"`: Path to your secrets.json file
- `--cache-from type=local,src=cache_dir --cache-to type=local,dest=cache_dir`: Configure `cache_dir` to cache keys.

#### Extracting the cached keys

If you wish to store the keys in the cache for future use, you can use the utility Dockerfile.read_cache to extract the
keys and update your `secrets.json` file.

1. Create the image for reading keys.
2. Run the image in the parent directory of `cache_dir`.

```
%> docker build --cache-from type=local,src=cache_dir -t read_cache -f Dockerfile.read_cache .
%> docker run --rm read_cache:latest
{output as JSON}
```

