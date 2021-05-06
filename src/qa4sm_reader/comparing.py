from qa4sm_reader.img import QA4SMImg
from qa4sm_reader.plot_utils import diff_plot, mapplot, boxplot, plot_spatial_extent, _format_floats
from qa4sm_reader.handlers import QA4SMDatasets, QA4SMMetricVariable, QA4SMMetric
import qa4sm_reader.globals as glob

from shapely.geometry import Polygon
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats

import warnings as warn

class ComparisonError(Exception):
    pass

# todo: take _get_pairwise outside plotting functions and handle at higher level

class QA4SMComparison():  #todo: optimize initialization (slow with large gridded files)
    """
    Class that provides comparison plots and table for a list of netCDF files. As initialising a QA4SMImage can
    take some time, the class can be updated keeping memory of what has already been initialized
    """
    def __init__(self, paths:list or str, extent:tuple=None, get_intersection:bool=True):
        """
        Initialise the QA4SMImages from the paths to netCDF files specified

        Parameters
        ----------
        paths : list or str
            list of paths or single path to .nc validation results files to use for the comparison
        extent : tuple, optional (default: None)
            Area to subset the values for.
            (min_lon, max_lon, min_lat, max_lat)
        get_intersection: bool, default is True
            Whether to get the intersection or union of the two spatial exents

        Attributes
        ----------
        comparison : dict
            dictionary with shape {path: (id, QA4SMImage)}
        ref : tuple
            QA4SMImage for the reference validation
        """
        self.paths = paths
        self.extent = extent

        self.comparison = self._init_imgs(extent=extent, get_intersection=get_intersection)
        self.ref = self._check_ref()
        self.union = not get_intersection

    def _init_imgs(self, extent=None, get_intersection=True) -> dict:
        """
        Initialize the QA4SMImages for the selected validation results files. If 'extent' is specified, this is used. If
        not, by default the intersection of results is taken and the images are initialized with it, unless 'get_union'
        is specified. In this case, only diff_table and diff_boxplots can be created (as only non-pairwise methods).

        Parameters
        ----------
        extent: tuple, optional. Default is None
            exent of stapial subset
        get_intersection : bool, optional. Default is True.
            if extent is not specified, we can either take the union or intersection of the original extents of the
            passed .nc files. This affects the diff_table and diff_boxplot methods, whereas the diff_corr, diff_mapplot
            and diff_plot ALWAYS consider the intersection.

        Returns
        -------
        comparison : dict or Image
            if more nc files are initialized, a dictionary with shape {path: (id, img)}. Otherwise, the single QASMImg
            initialized for the specified path
        """
        if self.single_image:
            if isinstance(self.paths, list):
                self.paths = self.paths[0]

            img = QA4SMImg(self.paths, extent=extent, empty=True)
            if not len(img.datasets.others) > 1:
                raise ComparisonError("A single validation was initialized, with a single "
                                      "satellite dataset. You should add another comparison term.")

            return img

        comparison = {}
        imgs = []
        if extent:
            try:
                for n, path in enumerate(self.paths):
                    img = QA4SMImg(path, extent=extent, empty=True)
                    imgs.append(img)
                    if path in comparison.keys():
                        raise ComparisonError("You are initializing the same validation twice")

                    comparison[path] = (n, img)

            except ComparisonError as e:
                e.message = "One of the initialised validation result files has no points in the given spatial subset:" \
                            "{}. \nYou should change subset to a valid one, or not pass any.".format(extent)
                raise e
        else:
            self.union = True  # save the state 'union' or 'intersection' to a class attribute
            if get_intersection:
                extent = self.get_extent(get_intersection=get_intersection)
                self.extent = extent
                self.union = False

            for n, path in enumerate(self.paths):
                img = QA4SMImg(path, extent=extent, empty=True)
                imgs.append(img)
                if path in comparison.keys():
                    raise ComparisonError("You are initializing the same validation twice")

                comparison[path] = (n, img)

        return comparison

    def init_union(self):
        """Re-initialize the images using the union of spatial extents"""
        self.comparison = self._init_imgs(extent=None, get_intersection=False)
        # make sure the new state is stored in the class attribute
        assert self.union

    def _check_ref(self) -> str:  # todo: should it work with different versions?
        """ Check that all initialized validation results have the same dataset as reference """
        if self.single_image:
            return self.comparison.datasets.ref

        for id, img in self.comparison.values():
            ref = img.datasets.ref
            if id != 0:
                if not ref == previous:
                    raise ComparisonError("The initialized validation results have different reference "
                                          "datasets. This is currently not supported")
            previous = ref

        return ref

    @property
    def common_metrics(self) -> list: # todo: it can only handle 2 images atm
        """Get list of metrics that can be used in the comparison"""
        if self.single_image:
            common_metrics = list(self.comparison.metrics.keys())
            common_metrics.remove("n_obs")  # cannot be compared
        else:
            common_metrics = []
            imgs = [i[1] for i in self.comparison.values()]
            for metric in imgs[0].metrics:
                if metric in imgs[1].metrics:
                    common_metrics.append(metric)

        return common_metrics

    @property
    def overlapping(self) -> bool:
        """Return True if the initialised validation results have overlapping spatial extents, else False"""
        if self.single_image:  # one validation is always on the same bounds
            return True

        polys = {}
        for id, img in self.comparison.values():  # get names and extents for all images
            minlon, maxlon, minlat, maxlat = img.extent
            bounds = [(minlon,minlat), (maxlon, minlat),
                      (maxlon, maxlat), (minlon, maxlat)]
            Pol = Polygon(bounds)
            name = "{}: ".format(id) + img.name
            polys[name] = Pol

        for n, Pol in enumerate(polys.values()):
            if n == 0:
                output = Pol  # define starting point
            output = output.intersection(Pol)

        return output.bounds != ()

    @property
    def single_image(self) -> bool:
        if isinstance(self.paths, str):
            return True
        else:
            return len(self.paths) == 1

    def _check_initialized(self, paths:str or list):
        """
        Check that the given path has been initialized in the class. Only working
        when a list of paths is initialized.

        Parameters
        ----------
        paths: str or list
            path(s) to be checked

        Raise
        -----
        KeyError : if path has not been initialized
        """
        hasnot = False
        if isinstance(paths, list):
            for path in paths:
                if not path in self.comparison.keys():
                    hasnot = True
                    break

        elif paths not in self.comparison.keys():
            path = paths
            hasnot = True

        if hasnot:
            raise KeyError ("The path {} has not been initialized in the QA4SMComparison class".format(path))

    def _check_pairwise(self):
        """
        Checks that the current initialized supports pairwise comparison methods

        Raise
        -----
        ComparisonException : if not
        """
        pairwise = True
        if len(list(self.comparison.keys())) > 2:
            pairwise = False

        else:
            for id, img in self.comparison.values():
                if img.datasets.n_datasets() > 2:
                    pairwise = False

        if not pairwise:
            raise ComparisonError("For pairwise comparison methods, only two "
                                  "validation results with two datasets each can be compared")

    @staticmethod
    def _combine_geometry(imgs:list, get_intersection:bool=True, visualize=False) -> tuple:
        """
        Return the union or the intersection of the spatial extents of the provided validations; in case of intersection,
        check that the validations are overlapping

        Parameters
        ----------
        imgs : list
            list with the QA4SMImg corresponding to the paths
        get_intersection : bool, optional. Default is True.
            if extent is not specified, we can either take the union or intersection of the original extents of the
            passed .nc files. This affects the diff_table and diff_boxplot methods, whereas the diff_corr, diff_mapplot
            and diff_plot ALWAYS consider the intersection.
        visualize: bool, optional. Default is False.
            If true, an image is produced to visualize the output

        Return
        ------
        extent: tuple
            spatial extent deriving from union or intersection of inputs
        """
        polys = {}
        for n, img in enumerate(imgs):  # get names and extents for all images
            minlon, maxlon, minlat, maxlat = img.extent
            bounds = [(minlon,minlat), (maxlon, minlat),
                      (maxlon, maxlat), (minlon, maxlat)]
            Pol = Polygon(bounds)
            name = "{}: ".format(n) + img.name
            polys[name] = Pol

        for n, Pol in enumerate(polys.values()):
            if n == 0:
                output = Pol  # define starting point
            if not get_intersection:  # get maximum extent
                output = output.union(Pol)
                where = "Union"
            else:  # get maximum common
                output = output.intersection(Pol)
                where = "Intersection"
                if not output:
                    raise ComparisonError("The spatial extents of the chosen validation results do "
                                          "not overlap. Set 'get_intersection' to False to perform the comparison.")
        name = '{} of the spatial subsets'.format(where)
        polys[name] = output

        minlon, minlat, maxlon, maxlat = output.bounds

        if visualize:
            title = "Spatial extent of the {} of the given validations".format(where)
            plot_spatial_extent(polys, output=name, title=title)

        return minlon, maxlon, minlat, maxlat

    def get_extent(self, get_intersection=True, visualize=False):
        """
        Method to get and visualize the output of 'union' or 'intersection' of the spatial extents.

        Parameters
        ----------
        get_intersection : bool, optional. Default is True.
            if extent is not specified, we can either take the union or intersection of the original extents of the
            passed .nc files. This affects the diff_table and diff_boxplot methods, whereas the diff_corr, diff_mapplot
            and diff_plot ALWAYS consider the intersection.
        visualize : bool, default is False
            create an image showing the output of this method
        """
        imgs = []
        for n, path in enumerate(self.paths):
            img = QA4SMImg(path, extent=None, load_data=False)
            imgs.append(img)

        return self._combine_geometry(
            imgs=imgs,
            get_intersection=get_intersection,
            visualize=visualize
        )

    def _get_varnames(self, metric):  # todo: get varnames for all metric groups
        """
        Predict the variable name of the initialized image from the metric name

        Parameters
        ----------
        metric: str
            name of metric

        Returns
        -------
        varlist: list
            list of the two variables
        """
        varlist = []
        varname_template = metric + "_between_{}-{}_and_{}-{}"
        if self.single_image:
            ds = self.comparison.datasets
            for id in ds.others_id:
                data = ds.dataset_metadata(ds.ref_id, "short_name") + \
                       ds.dataset_metadata(id, "short_name")
                varlist.append(
                    varname_template.format(*data)
                )
        else:
            for id, img in self.comparison.values():
                ds = img.datasets
                data = ds.dataset_metadata(ds.ref_id, "short_name") + \
                       ds.dataset_metadata(ds.others_id[0], "short_name")
                varlist.append(
                    varname_template.format(*data)
                )

        return varlist

    def _get_pairwise(self, metric:str) -> pd.DataFrame: #todo: create separate method for getting the difference and names
        """
        Get the data and names for pairwise comparisons, meaning: two validations with one satellite dataset each.
        In case that a single image is given, the comparison will be among the different satellite datasets.

        Parameters
        ----------
        metric: str
            name of metric to get data on

        Returns
        -------
        pair_df: pd.DataFrame
            Dataframe with the metric sets of values for each term of comparison
        """
        to_plot, names = [], []  # todo: improve names
        # check wether the comparison has one single image and the number of sat datasets
        if self.single_image and self.perform_checks():
            for n, varname in enumerate(self._get_varnames(metric)):
                to_plot.append(
                    self.comparison._ds2df(varnames=[varname])[varname]
                )
                names.append("{}-{}".format(n, varname))

        elif self.single_image and not self.perform_checks():
            pass  # todo: handle situation with mor than 2 non-reference datasets in validation

        else:
            for n, (varname, values) in enumerate(
                    zip(self._get_varnames(metric), self.comparison.values())
            ):
                id, img = values
                to_plot.append(
                    img._ds2df(varnames=[varname])[varname]
                )
                names.append("{}-{}".format(n, varname))

        pair_df = pd.concat(to_plot, axis=1)
        pair_df.columns = names
        pair_df["Difference"] = pair_df.iloc[:,0] - pair_df.iloc[:,1]

        return pair_df

    def perform_checks(self, overlapping=False, union=False, pairwise=False):
        """Performs selected checks and throws error is they're not passed"""
        if self.single_image:
            return len(self.comparison.datasets.others) <= 2

        # these checks are for multiple images
        else:
            if overlapping:
                if not self.overlapping:
                    raise ComparisonError("This method works only in case the initialized "
                                          "validations have overlapping spatial extents.")
            if union and not self.extent:  # todo: unexpected behavior here if union is initialized through init_union
                if self.union:
                    raise ComparisonError("If the comparison is based on the 'union' of spatial extents, "
                                          "this method cannot be called, as it is based on a point-by-point comparison")
            if pairwise:
                self._check_pairwise() # todo: handle other cases


    def diff_table(self, metrics:list) -> pd.DataFrame:  #todo: diff_table for single_image
        """
        Create a table where all the metrics for the different validation runs are compared

        Parameters
        ----------
        metrics: list
            list of metrics to create the table for
        """
        self.perform_checks(pairwise=True)
        table = {}
        for metric in metrics:
            ref = self._check_ref()["short_name"]
            units = glob._metric_description_HTML[metric].format(
                glob._metric_units_HTML[ref]
            )
            description = glob._metric_name[metric] + units
            medians = self._get_pairwise(metric).median()
            # a bit of a hack here
            table[description] = [
                medians[0],
                medians[1],
                medians[0] - medians[1]
            ]

        table = pd.DataFrame.from_dict(
            data=table,
            orient="index",
            columns=["first", "second", "difference"]
        )

        table = table.applymap(_format_floats)

        return table

    def diff_boxplot(self, metric:str, **kwargs):
        """
        Create a boxplot where two validations are compared. If the comparison is on the subsets union, then the
        difference is not shown.

        Parameters
        ----------
        metric: str
            metric from the .nc result file attributes that the plot is based on
        """
        self.perform_checks(pairwise=True)
        # prepare data
        boxplot_df = self._get_pairwise(metric=metric)
        # prepare axis name
        Metric = QA4SMMetric(metric)
        ref_ds = self.ref['short_name']
        um = glob._metric_description[metric].format(glob._metric_units[ref_ds])

        # plot data
        palette = sns.color_palette(palette=['paleturquoise', 'paleturquoise', 'pink'], n_colors=3)
        if self.union:
            palette = sns.color_palette(palette=['paleturquoise', 'paleturquoise'], n_colors=2)
            boxplot_df = boxplot_df.drop(columns=boxplot_df.columns[-1])
        fig, axes = boxplot(boxplot_df,
                            label= "{} {}".format(Metric.pretty_name, um),
                            figsize=(16,10),
                            **{'palette':palette})
        title_plot = "Boxplot comparison of {} {}".format(Metric.pretty_name, um)
        axes.set_title(title_plot, pad=glob.title_pad)

    def diff_plot(self, metric:str, **kwargs):
        """
        Create a Bland Altman plot where two validations are compared

        Parameters
        ----------
        metric: str
            metric from the .nc result file attributes that the plot is based on
        **kwargs : kwargs
            plotting keyword arguments
        """
        self.perform_checks(overlapping=True, union=True, pairwise=True)

        # get data and names
        df = self._get_pairwise(metric=metric).dropna()

        fig, axes = diff_plot(df)
        # get unit measures
        ref_name = self.ref['short_name']
        um = glob._metric_description[metric].format(glob._metric_units[ref_name])
        # set figure title
        Metric = QA4SMMetric(metric)
        title_plot = "Difference plot of {} {}".format(Metric.pretty_name, um)
        axes.set_title(title_plot, pad=glob.title_pad)

    def corr_plot(self, metric:str, **sns_kwargs):  #todo: colouring based on metadata
        """
        Correlation plot between two validation results, for a metric

        Parameters
        ----------
        metric: str
            metric from the .nc result file attributes that the plot is based on
        **sns_kwargs : kwargs
            plotting keyword arguments
        """
        self.perform_checks(overlapping=True, union=True, pairwise=True)

        # get data and names
        corrplot_df = self._get_pairwise(metric=metric).dropna()
        # get names right
        Metric = QA4SMMetric(metric)
        ref_ds = self.ref['short_name']
        um = glob._metric_description[metric].format(glob._metric_units[ref_ds])
        # plot regression
        slope, int, r, p, sterr = stats.linregress(corrplot_df.iloc[:,0], corrplot_df.iloc[:,1])
        fig, axes = plt.subplots(figsize=(16,10))
        ax = sns.regplot(x=corrplot_df.iloc[:, 0],
                         y=corrplot_df.iloc[:, 1],
                         label="Validation point",
                         line_kws={'label':"x ={}*y + {}, r: {}, p: {}".format(
                             *[round(i,2) for i in [slope, int, r, p]])},
                         **sns_kwargs)
        title_plot = "Correlation plot of {} {}".format(Metric.pretty_name, um)
        axes.set_title(title_plot, pad=glob.title_pad)
        plt.legend()

    def diff_mapplot(self, metric:str, diff_range:str='adjusted', **kwargs):
        """
        Create a pairwise mapplot of the difference between the validations, for a metric. Difference is other - reference

        Parameters
        ----------
        metric: str
            metric from the .nc result file attributes that the plot is based on
        diff_range: str, default is 'adjusted'
            if 'adjusted', colorbar goues from minimum to maximum of difference; if 'fixed', the colorbar goes from the
            maximum to the minimum difference range, by metric
        **kwargs : kwargs
            plotting keyword arguments
        """
        self.perform_checks(overlapping=True, union=True, pairwise=True)

        df_diff = self._get_pairwise(metric=metric).dropna()
        Metric = QA4SMMetric(metric)
        um = glob._metric_description[metric].format(glob._metric_units[self.ref['short_name']])
        # make mapplot
        cbar_label = "Difference between {} and {}".format(*df_diff.columns)
        fig, axes = mapplot(df_diff.iloc[:,2],  # todo: hack on ids
                            metric,
                            self.ref['short_name'],
                            diff_range=diff_range,
                            label=cbar_label)
        title_plot = "Overview of the difference in {} {}".format(Metric.pretty_name, um)
        axes.set_title(title_plot, pad=glob.title_pad)

    def wrapper(self, method:str, metric=None, **kwargs):
        """
        Call the method using a list of paths and the already initialised images

        Properties
        ----------
        method: str
            a method from the lookup table in diff_method
        metric: str
            metric from the .nc result file attributes that the plot is based on
        **kwargs : kwargs
            plotting keyword arguments
        """
        diff_methods_lut = {'boxplot': self.diff_boxplot,
                            'correlation': self.corr_plot,
                            'difference': self.diff_plot,
                            'mapplot': self.diff_mapplot}
        try:
            diff_method = diff_methods_lut[method]
        except IndexError as e:
            warn('Difference method not valid. Choose one of %s' % ', '.join(diff_methods_lut.keys()))
            raise e


        if not metric:
            raise ComparisonError("If you chose '{}' as a method, you should specify "
                                  "a metric (e.g. 'R').".format(method))

        return diff_method(
            metric=metric,
            **kwargs
        )
