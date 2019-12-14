# -*- coding: utf-8 -*-

from qa4sm_reader import globals
from parse import *
import warnings

def _build_fname_templ(n):
    """
    Create a template to parse for the file name, based on the dataset-version
    separation rule from globals.

    Parameters
    ----------
    n : int
        Total number of (reference and candidate) data sets in the file.

    Returns
    -------
    fname_templ : str
        Template for the file name to parse.
    """
    parts =[globals.ds_fn_templ.format(i='{i_ref}', ds='{ref}', var='{ref_var}')]
    for i in range(1, n):
        parts += [globals.ds_fn_templ.format(i='{i_ds%i}' % i, ds='{ds%i}' % i,
                                             var='{var%i}' % i)]
    return globals.ds_fn_sep.join(parts) + '.nc'

def _metr_grp(metric):
    for g in globals.metric_groups.keys():
        if metric in globals.metric_groups[g]:
            return g
    return None

class QA4SMAttributes(object):
    def __init__(self, global_attrs):
        """
        Parameters
        ----------
        global_attrs: dict
            Global attributes of the QA4SM validation result
        """
        self.meta = global_attrs
        self.other_dcs, self.ref_dc = self._dcs()

    def _dcs(self):
        """ Go through the metadata and find the dataset short names """
        ref_dc = self._ref_dc()
        dcs = dict()
        for k in self.meta.keys():
            parsed = parse(globals._ds_short_name_attr, k)
            if parsed is not None and len(list(parsed)) == 1:
                dc = list(parsed)[0]
                if dc != ref_dc:
                    dcs[dc] = k
        return dcs, ref_dc

    def _ref_dc(self):
        """ Get the short name of the reference dataset """
        val_ref = self.meta[globals._ref_ds_attr]
        ref_dc = parse(globals._ds_short_name_attr, val_ref)[0]
        return ref_dc

    def _dc_names(self, dc):
        """
        Get dataset meta data for the passed dc.

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
        short_name = self.meta[globals._ds_short_name_attr.format(dc)]
        pretty_name = self.meta[globals._ds_pretty_name_attr.format(dc)]
        short_version = self.meta[globals._version_short_name_attr.format(dc)]
        pretty_version = self.meta[globals._version_pretty_name_attr.format(dc)]

        return dict(short_name=short_name, pretty_name=pretty_name,
                    short_version=short_version, pretty_version=pretty_version)

    def get_all_names(self) -> (dict, dict):
        """
        Get 2 dictionaries of names, one for the ref names, one for the
        satellite ds names.
        """
        return self.get_ref_names(), self.get_other_names()

    def get_other_names(self) -> dict :
        """ Get a dictionary with names of the non-reference data sets"""
        ret = dict()
        for dc in self.other_dcs:
            ret[dc] = self._dc_names(dc)
        return ret

    def get_ref_names(self) -> dict :
        """ Get a dictionary with names of the non-reference data sets"""
        return self._dc_names(self._ref_dc())


class QA4SMDataAttributes(QA4SMAttributes):
    def __init__(self, id, short_name, global_attrs):
        """
        QA4SMDataAttributes handler for metdata lookup

        Parameters
        ----------
        id : int
            Id of the dataset as in the VARIABLE NAME (not as in the attributes)
        short_name : str
            Short name of the dataset as in the variable name
        global_attrs : dict
            Global attributes of the results file, for lookup
        """
        super(QA4SMDataAttributes, self).__init__(global_attrs)
        self.id = id
        assert short_name == self.names_from_attrs('short_name')
        self.short_name = short_name
        self.version = self.names_from_attrs('short_version')

    def _id2dc(self) -> int:
        # TODO: fix this make it fixable via globals
        return self.id - 1

    def names_from_attrs(self, element='all'):
        """
        Get names for this dataset

        Parameters
        ----------
        elements : str or list
            'all' or 'short_name' or 'pretty_name' or 'short_version' or
            'pretty_version'

        Returns
        -------
        dict or str : names
            The names as a dictionary
        """
        if isinstance(element, str):
            element = [element]

        dc = self._id2dc()
        names = self._dc_names(dc=dc)
        if element == ['all']:
            element = list(names.keys())
        else:
            if not all([e in list(names.keys()) for e in element]):
                raise ValueError("Elements must be either 'all' or one or "
                                 "mutliple of {}".format(
                    ', '.join(list(names.keys()))))

        if len(element) == 1:
            return names[element[0]]
        else:
            return {e: names[e] for e in element}

    def pretty_name(self) -> str:
        """ get the pretty name, from meta or from globals.py"""
        try:
            return self.names_from_attrs('pretty_name')
        except AttributeError: # todo: what exception
            warnings.warn('pretty name not found in metadata, fallback to globals.py')
            if self.short_name in globals._dataset_pretty_names.keys():
                return globals._dataset_pretty_names[self.short_name]
            else:
                warnings.warn('pretty name also not found in globals.py, use short name')
                return self.short_name

    def pretty_version(self) -> str:
        """ get the pretty version name, from meta or from globals.py"""
        try:
            return self.names_from_attrs('pretty_version')
        except AttributeError:
            warnings.warn('pretty version not found in metadata, fallback to globals.py')
            if self.version in globals._dataset_version_pretty_names.keys():
                return globals._dataset_version_pretty_names[self.version]
            else:
                warnings.warn('pretty version also not found in globals, use version')
                return self.version


class QA4SMMetricVariable(object):

    def __init__(self, name, data, global_attrs):
        """
        Validation results for a validation metric and a combination of datasets.

        Parameters
        ---------
        name : str
            Name of the variable
        data : pd.DataFrame
            Data of the variable
        global_attrs : # todo: give the attrs object instead?

        """
        self.name = name
        self.attrs = global_attrs
        self.metric, self.g, self.parts = self._parse_name()

        if not self.ismetr():
            raise IOError(name, '{} is not in form of a QA4SM metric variable.')

        self.ref_ds, self.other_dss, self.metric_ds = self._ds_from_name()
        self.data = data

    def _parse_name(self) -> (str, int, dict):
        """ parse the name to get the metric """
        metr_groups = list(globals.metric_groups.keys())
        for g in metr_groups:
            templ_d = globals.var_name_ds_sep[g]
            pattern = '{}{}'.format(globals.var_name_metric_sep[g],
                                    templ_d if templ_d is not None else '')
            parts = parse(pattern, self.name)

            if parts is not None and parts['metric'] in globals.metric_groups[g]:
                return parts['metric'], g, parts.named
        return None, None, None

    def _ds_from_name(self) -> (QA4SMDataAttributes, list, QA4SMDataAttributes):
        """ get the datasets from the current variable"""
        if self.g == 0:
            return None, None, None
        else:
            dss = []
            ref_ds = QA4SMDataAttributes(self.parts['ref_id'], self.parts['ref_ds'], self.attrs)
            dss.append(QA4SMDataAttributes(self.parts['sat_id0'], self.parts['sat_ds0'], self.attrs))
            if self.g == 3:
                dss.append(QA4SMDataAttributes(self.parts['sat_id1'], self.parts['sat_ds1'], self.attrs))
                mds = QA4SMDataAttributes(self.parts['mds_id'], self.parts['mds'], self.attrs)
            else:
                mds = None
            return ref_ds, dss, mds

    def ismetr(self) -> bool:
        """ Check whether this is a metric variable """
        return True if self.metric is not None else False

    def isempty(self):
        """ Check whether the data is empty or not yet loaded """
        if self.data is None or self.data.empty:
            return True

    def get_varmeta(self):
        """
        Get the dataset names based on metadata information

        Returns
        -------
        ref_meta : tuple
            Names for the reference dataset
        dss_meta : list of tuples
            Names for the satellite datasets
        mds_meta : tuple
            Names for the metric dataset (TC only)
        """
        if self.ref_ds is not None:
            ref_meta = (self.ref_ds.id, self.ref_ds.names_from_attrs('all'))
        else:
            ref_meta = None
        if self.other_dss is not None:
            dss_meta = [(ds.id, ds.names_from_attrs('all')) for ds in self.other_dss]
        else:
            dss_meta = None
        if self.metric_ds is not None:
            mds_meta = (self.metric_ds.id, self.metric_ds.names_from_attrs('all'))
        else:
            mds_meta = None
        return {'ref' : ref_meta, 'dss': dss_meta, 'mds': mds_meta}




if __name__ == '__main__':
    import xarray as xr
    ds = xr.load_dataset(r"H:\code\qa4sm-reader\tests\test_data\basic\4-ERA5.swvl1_with_1-C3S.sm_with_2-ASCAT.sm_with_3-SMOS.Soil_Moisture.nc")
    var1 = QA4SMMetricVariable('n_obs', ds.attrs)
    var2 = QA4SMMetricVariable('RMSD_between_4-ERA5_and_1-C3S', ds.attrs)
    var1.get_varmeta()
    var2.get_varmeta()

    ds = xr.load_dataset(r"H:\code\qa4sm-reader\tests\test_data\tc\3-ERA5_LAND.swvl1_with_1-C3S.sm_with_2-ASCAT.sm.nc")
    var1 = QA4SMMetricVariable('n_obs', ds.attrs)
    var2 = QA4SMMetricVariable('snr_1-C3S_between_3-ERA5_LAND_and_1-C3S_and_2-ASCAT', ds.attrs)
    a1,b1,c1 =var1.get_varmeta()
    a2,b2,c2 =var2.get_varmeta()

