import urllib2
from xml.etree import cElementTree as ET

from osc import oscerr
from osc.core import makeurl
from osc.core import http_GET


def _is_int(x):
    return isinstance(x, int) or x.isdigit()


class RequestFinder(object):

    def __init__(self, api):
        """
        Store the list of submit request together with the source project

        Example:
             {
                 212454: {
                     'project': 'openSUSE:Factory',
                 },
                 223870: {
                     'project': 'openSUSE:Factory',
                     'staging': 'openSUSE:Factory:Staging:A',
                 }
             }
        """
        self.api = api
        self.srs = {}

    def find_request_id(self, request_id):
        """
        Look up the request by ID to verify if it is correct
        :param request_id: ID of the added request
        """

        if not _is_int(request_id):
            return False

        url = makeurl(self.api.apiurl, ['request', str(request_id)])
        try:
            f = http_GET(url)
        except urllib2.HTTPError:
            return None

        root = ET.parse(f).getroot()

        if root.get('id', None) != str(request_id):
            return None

        project = root.find('action').find('target').get('project')
        if (project != 'openSUSE:{}'.format(self.api.opensuse) and not project.startswith('openSUSE:{}:Staging:'.format(self.api.opensuse))):
            msg = 'Request {} is not for openSUSE:{}, but for {}'
            msg = msg.format(request_id, self.api.opensuse, project)
            raise oscerr.WrongArgs(msg)
        self.srs[int(request_id)] = {'project': project}

        return True

    def find_request_package(self, package):
        """
        Look up the package by its name and return the SR#
        :param package: name of the package
        """

        query = 'states=new,review,declined&project=openSUSE:{}&view=collection&package={}'
        query = query.format(self.api.opensuse, urllib2.quote(package))
        url = makeurl(self.api.apiurl, ['request'], query)
        f = http_GET(url)

        root = ET.parse(f).getroot()

        last_rq = None
        for sr in root.findall('request'):
            # Check the package matches - OBS is case insensitive
            rq_package = sr.find('action').find('target').get('package')
            if package.lower() != rq_package.lower():
                continue

            request = int(sr.get('id'))
            state = sr.find('state').get('name')

            self.srs[request] = {'project': 'openSUSE:{}'.format(self.api.opensuse), 'state': state}

            if last_rq:
                if self.srs[last_rq]['state'] == 'declined':
                    # ignore previous requests if they are declined
                    # if they are the last one, it's fine to return them
                    del self.srs[last_rq]
                else:
                    msg = 'There are multiple requests for package "{}": {} and {}'
                    msg = msg.format(package, last_rq, request)
                    raise oscerr.WrongArgs(msg)

            # Invariant of the loop: request is the max request ID searched so far
            assert last_rq < request, 'Request ID do not increase monotonically'

            last_rq = request

        return last_rq

    def find_request_project(self, source_project):
        """
        Look up the source project by its name and return the SR#(s)
        :param source_project: name of the source project
        """

        query = 'states=new,review&project=openSUSE:{}&view=collection'.format(self.api.opensuse)
        url = makeurl(self.api.apiurl, ['request'], query)
        f = http_GET(url)
        root = ET.parse(f).getroot()

        ret = None
        for sr in root.findall('request'):
            for act in sr.findall('action'):
                src = act.find('source')
                if src is not None and src.get('project') == source_project:
                    request = int(sr.attrib['id'])
                    state = sr.find('state').get('name')
                    self.srs[request] = {'project': 'openSUSE:{}'.format(self.api.opensuse), 'state': state}
                    ret = True

        return ret

    def find(self, pkgs):
        """
        Search for all various mutations and return list of SR#s
        :param pkgs: mesh of argumets to search for

        This function is only called for its side effect.
        """
        for p in pkgs:
            if self.find_request_package(p):
                continue
            if self.find_request_id(p):
                continue
            if self.find_request_project(p):
                continue
            raise oscerr.WrongArgs('No SR# found for: {}'.format(p))

    def find_via_stagingapi(self, pkgs):
        """
        Search for all various mutations and return list of SR#s. Use
        and instance of StagingAPI to direct the search, this makes
        sure that the SR# are inside a staging project.
        :param pkgs: mesh of argumets to search for

        This function is only called for its side effect.
        """

        for p in pkgs:
            found = False
            for staging in self.api.get_staging_projects():
                if _is_int(p) and self.api.get_package_for_request_id(staging, p):
                    self.srs[int(p)] = {'staging': staging}
                    found = True
                    continue
                else:
                    rq = self.api.get_request_id_for_package(staging, p)
                    if rq:
                        self.srs[rq] = {'staging': staging}
                        found = True
                        continue
            if not found:
                raise oscerr.WrongArgs('No SR# found for: {}'.format(p))

    @classmethod
    def find_sr(cls, pkgs, api):
        """
        Search for all various mutations and return list of SR#s
        :param pkgs: mesh of argumets to search for
        :param api: StagingAPI instance
        """
        finder = cls(api)
        finder.find(pkgs)
        return finder.srs

    @classmethod
    def find_staged_sr(cls, pkgs, api):
        """
        Search for all various mutations and return a single SR#s.
        :param pkgs: mesh of argumets to search for (SR#|package name)
        :param api: StagingAPI instance
        """
        finder = cls(api)
        finder.find_via_stagingapi(pkgs)
        return finder.srs
