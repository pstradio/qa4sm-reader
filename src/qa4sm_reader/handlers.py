# -*- coding: utf-8 -*-

from qa4sm_reader import globals
from parse import *
import warnings

class QA4SMDatasets():
    """Class that provides information on all datasets in the results file"""

    def __init__(self, global_attrs):
        """
        Parameters
        ----------
        global_attrs: dict
            Global attributes of the QA4SM validation result
        """
        # attributes of the result file
        self.meta = global_attrs
        self._get_offset()
        self.others = self.get_others()

    def _ref_dc(self) -> int:
        """
        Get the id of the reference dataset from the results file

        Returns
        -------
        ref_dc : int
        """
        ref_dc = 0
        if globals._ref_ds_attr in self.meta.keys():
            val_ref = self.meta[globals._ref_ds_attr]
            ref_dc = parse(globals._ds_short_name_attr, val_ref)[0]

        return ref_dc

    def _get_offset(self) -> int:
        """Check that the id number given to the reference is 0, change the ids if not"""
        self._offset_id_dc = 0
        if self._ref_dc() != 0:
            self._offset_id_dc = -1

    def _dcs(self) -> dict:
        """
        Return the ids and attribute key for each dataset that is not the reference


        Returns
        -------
        dcs: dict
            dictionary of the shape {id : attribute key}
        """
        dcs = {}
        for k in self.meta.keys():
            parsed = parse(globals._ds_short_name_attr, k)
            if parsed is not None and len(list(parsed)) == 1:
                dc = list(parsed)[0]
                if dc != self._ref_dc():
                    dcs[dc] = k

        return dcs

    def _dc_names(self, dc:int) -> dict:
        """
        Get dataset meta values for the passed dc

        Parameters
        ----------
        dc : int
            The id of the dataset as in the global metadata of the results file

        Returns
        -------
        names : dict
            short name, pretty_name and short_version and pretty_version of the
            dc dataset.
        """
        names = {}

        names['short_name'] = self.meta[globals._ds_short_name_attr.format(dc)]
        names['pretty_name'] = self.meta[globals._ds_pretty_name_attr.format(dc)]
        names['short_version'] = self.meta[globals._version_short_name_attr.format(dc)]
        names['pretty_version'] = self.meta[globals._version_pretty_name_attr.format(dc)]
        names['pretty_title'] = names['pretty_name'] + ' ({})'.format(names['pretty_version'])
        # todo: create condition if key not found in the attrs (take from global.py)

        return names

    def _id2dc(self, id:int) -> int:
        """
        Offset ids according to the offset_id_dc value

        Parameters
        ----------
        id: int
            # todo: description
        """
        return id + self._offset_id_dc

    def n_datasets(self) -> int:
        """
        Counts the total number of datasets (reference + others)
        """
        n_others = len(self._dcs().keys())

        return n_others + 1

    def get_others(self) -> list:
        """Get a list with the datset metadata for oll the non-reference datasets"""
        others_meta = []
        for dc in self._dcs():
            dc_name = self._dc_names(dc)
            others_meta.append(dc_name)

        return others_meta

    def dataset_metadata(self, id:int, element:str or list=None) -> tuple:
        """
        Get the metadata for the dataset specified by the id and short_name

        Parameters
        ----------
        elements : str or list
            one of: 'all','short_name','pretty_name','short_version','pretty_version'

        Returns
        -------
        meta: tuple
            tuple with (dataset id, names dict)
        """
        # todo: check use of dc/id
        dc = self._id2dc(id=id)
        names = self._dc_names(dc=dc)

        if element is None:
            meta = names

        elif isinstance(element, str):
            if not element in names.keys():
                raise ValueError("Elements must be one of '{}'".format(', '.join(names.keys()))) #todo: check error

            meta = names[element]

        else:
            meta = {e: names[e] for e in element}

        return (id, meta)

class QA4SMMetricVariable():
    """ Class that describes a metric variable, i.e. the metric for a specific set of Datasets"""

    def __init__(self, varname, global_attrs, values=None):
        """
        Validation results for a validation metric and a combination of datasets.

        Parameters
        ---------
        name : str
            Name of the variable
        global_attrs : dict
            Global attributes of the results.
        values : pd.DataFrame, optional (default: None)
            Values of the variable, to store together with the metadata.

        Attributes
        ----------
        metric : str
            metric name
        g : int
            group number
        ref_df : QA4SMNamedAttributes
            reference dataset
        other_dss : list
            list of QA4SMNamedAttributes for the datasets that are not reference
        metric_ds : QA4SMNamedAttributes
            metric-relative dataset in case of TC metric
        """

        self.varname = varname
        self.attrs = global_attrs
        self.values = values

        self.metric, self.g, self.parts = self._parse_varname()
        self.Datasets = QA4SMDatasets(self.attrs)
        # exclude lat, lon, idx, gpi, time, _row_size todo: should be excluded more upstream
        if self.g is not None:
            self.Metric = QA4SMMetric(self.metric)
            self.ref_ds, self.metric_ds, self.other_ds = self.get_varmeta()
            self.pretty_name = self._pretty_name()

    def isempty(self) -> bool:
        """ Check whether values are associated with the object or not """
        if self.values is None or self.values.empty:

            return True

    def _pretty_name(self):
        """ Create a nice name for the variable """
        name = globals._variable_pretty_name[self.g]

        if self.g == 0:
            return name.format(self.metric)

        elif self.g == 2:
            return name.format(self.Metric.pretty_name, self.metric_ds[1]['pretty_title'],
                               self.ref_ds[1]['pretty_title'])
        elif self.g == 3:
            return name.format(self.Metric.pretty_name, self.metric_ds[1]['pretty_title'],
                               self.ref_ds[1]['pretty_title'], self.other_ds[1]['pretty_title'])

    def _parse_varname(self) -> (str, int, dict):
        """
        Parse the name to get the metric, group and variable data

        Returns
        -------
        metric : str
            metric name
        g : int
            group
        parts : dict
            dictionary of MetricVariable data
        """
        metr_groups = list(globals.metric_groups.keys())
        # check which group it belongs to
        for g in metr_groups:
            template = globals.var_name_ds_sep[g]
            if template is None:
                template = ''
            pattern = '{}{}'.format(globals.var_name_metric_sep[g], template)
            # parse infromation from pattern and name
            parts = parse(pattern, self.varname)

            if parts is not None and parts['metric'] in globals.metric_groups[g]:
                return parts['metric'], g, parts.named

        return None, None, None

    def get_varmeta(self) -> (tuple, tuple, tuple):
        """
        Get the datasets from the current variable. Each dataset is provided with shape
        (id, dict{names})

        Returns
        -------
        ref_ds : id, dict
            reference dataset
        mds : id, dict
            this is the dataset for which the metric is calculated
        dss : id, dict
            this is the additional dataset in TC variables
        """
        if self.g == 0:
            ref_ds = self.Datasets.dataset_metadata(self.Datasets._ref_dc())
            mds, dss = None, None

        else: # todo: update for new structure
            ref_ds = self.Datasets.dataset_metadata(self.parts['ref_id'])
            mds = self.Datasets.dataset_metadata(self.parts['sat_id0'])
            dss = None
            # if metric is TC, add third dataset
            if self.g == 3:
                mds = self.Datasets.dataset_metadata(self.parts['mds_id'])
                dss = self.Datasets.dataset_metadata(self.parts['sat_id1'])
                if dss == mds:
                    dss = self.Datasets.dataset_metadata(self.parts['sat_id0'])

        return ref_ds, mds, dss

class QA4SMMetric():
    """ Class for validation metric """
    def __init__(self, name, variables_list=None):

        self.name = name
        self.pretty_name = globals._metric_name[self.name]

        if variables_list:
            self.variables = variables_list
            self.g = self._get_attribute('g')
            self.attrs = self._get_attribute('attrs')

    def _get_attribute(self, attr:str):
        """
        Absorb Var attribute when is equal for all variables (e.g. group, reference dataset)

        Parameters
        ----------
        attr : str
            attribute name for the class QA4SMMetricVariable

        Returns
        -------
        value : attribute value
        """
        for n, Var in enumerate(self.variables):
            value = getattr(Var, attr)
            if n != 0:
                assert value == previous, "The attribute {} is not equal in all variables".format(attr)
            previous = value

        return value
