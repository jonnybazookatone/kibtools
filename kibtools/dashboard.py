#!/usr/bin/env python
# encoding: utf-8

"""
Modified from https://github.com/jim-davis/kibana-helper-scripts
"""

import os
import glob
import json
import config
import tarfile
import logging
import logging.config
import requests

logging.config.dictConfig(config.LOGGING)
logger = logging.getLogger()

def parse_visualizations(dashboard):
    """
    Parse the visualizations from a dashboard
    :param dashboard: JSON dashboard response
    :return: list of visualization names
    """
    return [panel['id'] for panel in json.loads(dashboard['panelsJSON'])]

def get_dashboards(cluster):
    """
    GET all the saved dashboards

    :param cluster: cluster details
    :return: list of dictionaries
    """
    url = 'http://{ip_address}:{port}/{index}/dashboard/_search'.format(
        ip_address=cluster['ip_address'],
        port=cluster['port'],
        index=cluster['index'],
    )

    response = requests.get(url)
    dashboards = json.loads(response.text).get('hits', {}).get('hits', {})

    dashboards = [
        dict(name=db['_id'],
             source=db['_source'],
             visualizations=parse_visualizations(db['_source'])
             ) for db in dashboards
        ]

    return dashboards

def get_visualizations(cluster):
    """
    GET all the saves visualizations

    :param cluster: cluster details
    :return: list of dictionaries
    """
    url = 'http://{ip_address}:{port}/{index}/visualization/_search'.format(
        ip_address=cluster['ip_address'],
        port=cluster['port'],
        index=cluster['index'],
    )

    response = requests.get(url)
    visualizations = json.loads(response.text).get('hits', {}).get('hits', {})

    visualizations = [
        dict(name=viz['_id'],
             source=viz['_source'],
             searches=viz['_source']['savedSearchId']
             ) for viz in visualizations
        ]

    return visualizations

def get_searches(cluster):
    """
    GET all the saved searches

    :param cluster: cluster details
    :return: list of dictionaries
    """
    url = 'http://{ip_address}:{port}/{index}/search/_search'.format(
        ip_address=cluster['ip_address'],
        port=cluster['port'],
        index=cluster['index'],
    )

    response = requests.get(url)
    searches = json.loads(response.text).get('hits', {}).get('hits', {})

    searches = [
        dict(name=search['_id'],
             source=search['_source']
             ) for search in searches
        ]

    return searches

def save_all_types(cluster, output_directory):
    """
    Collect all the relevants types and save them to an output directory

    :param cluster: cluster details
    :param output_directory: path to output directory
    """

    # Make the output directory
    if not os.path.isdir(output_directory):
        os.mkdir(output_directory)

    save_all = dict(
        dashboard=get_dashboards(cluster=cluster),
        visualization=get_visualizations(cluster=cluster),
        search=get_searches(cluster=cluster)
    )

    logger.info('Saving dashboard content to: {0}'.format(output_directory))
    for save_type in save_all:

        # Skip this if there are no objects
        if len(save_all[save_type]) == 0:
            continue

        # If the folder does not exist
        sub_folder = '{path}/{sub_path}'.format(
            path=output_directory,
            sub_path=save_type
        )

        if not os.path.isdir(sub_folder):
            os.mkdir(sub_folder)

        logger.info('Saving files for type: {0}'.format(save_type))
        for objects in save_all[save_type]:
            output_file = '{path}{sub_path}/{file}.json'.format(
                path=output_directory,
                sub_path=save_type,
                file=objects['name']
            )
            with open(output_file, 'w') as output_json:
                json.dump(objects['source'], output_json)

            logger.info('...... file object: {0}'.format(objects['name']))

def push_object(cluster, push_type, push_name, push_source):
    """
    Push an object to the elasticsearch cluster

    :param cluster: cluster details
    :param push_type: type of the object: dashboard, visualization, search
    :param push_name: name of object
    :param push_source: source of object

    :return: response message from elasticsearch
    """
    url = 'http://{ip_address}:{port}/{index}/{type}/{name}'.format(
        ip_address=cluster['ip_address'],
        port=cluster['port'],
        index=cluster['index'],
        type=push_type,
        name=push_name
    )
    response = requests.post(url, data=push_source)
    return response

def push_all_from_disk(cluster, input_directory):
    """
    Look at the input_directory for expected folders:
      - search, visualization, dashboard
    And push any JSON file that exists inside to elasticsearch

    :param cluster: cluster details
    :param input_directory: directory that contains all types
    """

    if not os.path.isdir(input_directory):
        raise IOError('Folder does not exist')

    logger.info('Using folder: {0}'.format(input_directory))

    for push_type in ['search', 'visualization', 'dashboard']:
        sub_path = '{path}/{sub_path}'.format(
            path=input_directory,
            sub_path=push_type
        )
        if not os.path.isdir(sub_path):
            continue
        files = glob.glob('{0}/*'.format(sub_path))

        if len(files) == 0:
            continue

        logger.info('Pushing files for type: {0}'.format(push_type))
        for file_object in files:
            with open(file_object, 'r') as input_json_file:
                push_source = json.load(input_json_file)

            push_name = push_source['title']
            response = push_object(
                cluster=cluster,
                push_type=push_type,
                push_name=push_name,
                push_source=push_source
            )

            logger.info('....... file object: {0}'.format(push_name))
            logger.info('Response from ES: {0}'.format(response))

def push_to_s3(input_directory, s3_details):
    """
    Push the files on disk to S3 storage

    :param input_directory: input directory
    :param s3_details: details about AWS S3
    """
    tar_file = '{0}/dashboard.tar.gz'.format(input_directory)
    with tarfile.open(tar_file, 'w:gz') as out_tar:
        out_tar.add(input_directory)
    logger.info('Made a gzipped tarbarball: {0}'.format(tar_file))

    url = '{schema}://{bucket}.{host}/{objects}'.format(
        schema=s3_details['schema'],
        bucket=s3_details['bucket'],
        host=s3_details['host'],
        objects='dashboard.tar.gz'
    )

    logger.info('Pushing to S3 storage: {0}'.format(url))
    files = {'file': open(tar_file, 'rb')}
    response = requests.put(url, files=files)

    logger.info('S3 response: {0}'.format(response))
    return response

def pull_from_s3(output_directory, s3_details):
    """
    Pull files from S3 storage and unpack

    :param output_directory: output directory
    :param s3_details: details about AWS S3
    """

    url = '{schema}://{bucket}.{host}/{objects}'.format(
        schema=s3_details['schema'],
        bucket=s3_details['bucket'],
        host=s3_details['host'],
        objects='dashboard.tar.gz'
    )
    logger.info('Pulling file from S3 storage: {0}'.format(url))

    # Download the file in chunk sizes of 1024
    # see http://stackoverflow.com/questions/
    # 13137817/how-to-download-image-using-requests
    response = requests.get(url, stream=True)

    chunk_size = 1024
    if response.status_code == 200:
        with open('/tmp/dashboard.tar.gz', 'wb') as f:
            for chunk in response.iter_content(chunk_size):
                logger.info('Writing chunk of size: {0}'.format(chunk_size))
                f.write(chunk)

    logger.info('Opening tar file to: {0}'.format(output_directory))
    tar_file = tarfile.open('/tmp/dashboard.tar.gz', 'r')
    tar_file.extractall(output_directory)

    os.remove('/tmp/dashboard.tar.gz')

if __name__ == '__main__':

    # For each dashboard get the relevant dashboard
    print 'TBD'