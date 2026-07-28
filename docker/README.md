# crickettracker

Cricket Tracker is a local-first Streamlit application for recording and exploring cricket competitions, fixtures, results, innings summaries and league standings.

The initial release supports The Hundred men's and women's competitions, including structured match results, toss details, innings summaries, configurable competition rules, automatic league tables and net run rate calculations.

The application uses an independent SQLite database and supports CSV import and export for its principal data types.

This image provides a self-contained Docker deployment of Cricket Tracker. For fuller details about the application, its features and supported data model, see the [Cricket Tracker repository on GitHub](https://github.com/davewalker5/CricketTracker).

## Getting Started

### Prerequisities

In order to run this image you'll need docker installed.

- [Windows](https://docs.docker.com/windows/started)
- [OS X](https://docs.docker.com/mac/started/)
- [Linux](https://docs.docker.com/linux/started/)

### Usage

#### Container Parameters

The following "docker run" parameters are recommended when running the crickettracker image:

| Parameter  | Value                          | Purpose                                                 |
| ---------- | ------------------------------ | ------------------------------------------------------- |
| -d         | -                              | Run as a background process                             |
| -v         | /local:/var/opt/crickettracker | Mount the host folder containing the SQLite database    |
| -p         | 80:8501                        | Expose the container's port 8501 as port 80 on the host |
| --platform | linux/amd64                    | Target architecture ; this must be linux/amd64          |
| --rm       | -                              | Remove the container automatically when it stops        |
| --name     | crickettracker                 | Name of the container once running                      |

For example:

```shell
docker run -d -v /local:/var/opt/crickettracker/ -p 80:8501 --platform linux/amd64  --name crickettracker --rm davewalker5/crickettracker:latest
```

The "/local" path given to the -v argument is described, below, and should be replaced with a value appropriate for the host running the container. Similarly, the port number "80" can be replaced with any available port on the host.

### Volumes

The description of the container parameters, above, specifies that a folder containing the SQLite database file for the application is mounted in the running container, using the "-v" parameter.

That folder should contain a SQLite database named "crickettracker.db".

#### Running the Application

To run the image, enter the following commands, substituting "/local" for the host folder containing the SQLite database, as described:

```shell
docker run -d -v /local:/var/opt/crickettracker/ -p 80:8501 --platform linux/amd64  --name crickettracker --rm davewalker5/crickettracker:latest
```

The "/local" path given to the -v argument is described, below, and should be replaced with a value appropriate for the host running the container. Similarly, the port number "80" can be replaced with any available port on the host.

Once the container is running, browse to the following URL on the host:

```
http://localhost:80
```

Replace port 80 with the selected port. You should see the plate maintenance entry page.

## Find Us

- [Cricket Tracker on GitHub](https://github.com/davewalker5/CricketTracker)

## Versioning

For the versions available, see the [tags on this repository](https://github.com/davewalker5/CricketTracker/tags).

## Authors

- **Dave Walker** - _Initial work_ -

See also the list of [contributors](https://github.com/davewalker5/CricketTracker/contributors) who
participated in this project.

## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/davewalker5/CricketTracker/blob/master/LICENSE) file for details.
