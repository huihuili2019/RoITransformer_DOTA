# --------------------------------------------------------
# Deformable Convolutional Networks
# Copyright (c) 2017 Microsoft
# Licensed under The Apache-2.0 License [see LICENSE for details]
# Modified by Haozhi Qi, from py-faster-rcnn (https://github.com/rbgirshick/py-faster-rcnn)
# --------------------------------------------------------

"""
Pascal VOC database
This class loads ground truth notations from standard Pascal VOC XML data formats
and transform them into IMDB format. Selective search is used for proposals, see roidb
function. Results are written as the Pascal VOC format. Evaluation is based on mAP
criterion.
"""

import cPickle
import os
import numpy as np

from imdb import IMDB
import cv2
import zipfile
from bbox.bbox_transform import bbox_overlaps, bbox_transform, get_best_begin_point_wrapp
from PIL import Image
import codecs
import sys
# TODO: change it
sys.path.insert(0, r'../../')
# this_dir = os.path.dirname(__file__)
# sys.path.insert(0, os.path.join(this_dir, '..', '..', 'fpn'))
import pdb

# pdb.set_trace()
# from dota_kit.ResultMerge import *
from dota_kit.ResultMerge_multi_process import *

# the target of this class is to get DOTA roidb
class DOTA(IMDB):
    def __init__(self, image_set, root_path, data_path, result_path=None, mask_size=-1, binary_thresh=None):
        """
        fill basic information to initialize imdb
        :param image_set: train, test etc.
        :param root_path: 'selective_search_data' and 'cache'
        :param data_path: data and results
        :return: imdb object
        """
        self.image_set = image_set
        super(DOTA, self).__init__('DOTA', self.image_set, root_path, data_path, result_path)  # set self.name

        self.root_path = root_path
        self.data_path = data_path

        self.classes = ['__background__',  # always index 0
                        'plane', 'baseball-diamond',
                        'bridge', 'ground-track-field',
                        'small-vehicle', 'large-vehicle',
                        'ship', 'tennis-court',
                        'basketball-court', 'storage-tank',
                        'soccer-ball-field', 'roundabout',
                        'harbor', 'swimming-pool',
                        'helicopter']
        self.num_classes = len(self.classes)
        ## index changed to be basename
        self.image_set_index = self.load_image_set_index()
        self.num_images = len(self.image_set_index)
        print 'num_images', self.num_images
        self.mask_size = mask_size
        self.binary_thresh = binary_thresh

        self.config = {'comp_id': 'comp4',
                       'use_diff': False,
                       'min_size': 2}

    def load_image_set_index(self):
        """
        find out which indexes correspond to given image set (train or val)
        :return:
        """
        image_set_index_file = os.path.join(self.data_path, self.image_set + '.txt')
        assert os.path.exists(image_set_index_file), 'Path does not exist: {}'.format(image_set_index_file)
        with open(image_set_index_file, 'r') as f:
            lines = f.readlines()
        image_lists = [line.strip() for line in lines]
        #image_lists = [os.path.join(self.data_path, 'images', line.strip() + '.jpg') for line in lines]
        return image_lists

    def image_path_from_index(self, index):
        """
        given image index, find out full path
        :param image_name: image name in the data dir
        :return: full path of this image
        """
        # hint: self.image_set means 'train' or 'test'
        # TODO: when data ready, the entrance here should be changed
        # Now, it has been changed
        # image_file = os.path.join(self.data_path, self.image_set, index)
        image_file = os.path.join(self.data_path, 'images', index + '.png')
        assert os.path.exists(image_file), 'Path does not exist: {}'.format(image_file)
        return image_file

    def gt_roidb(self):
        """
        return ground truth image regions database
        :return: imdb[image_index]['boxes', 'gt_classes', 'gt_overlaps', 'flipped']
        """
        cache_file = os.path.join(self.cache_path, self.name + '_gt_roidb.pkl')
        if os.path.exists(cache_file):
            with open(cache_file, 'rb') as fid:
                roidb = cPickle.load(fid)
            print '{} gt roidb loaded from {}'.format(self.name, cache_file)
            return roidb

        gt_roidb = [self.load_annotation(index) for index in self.image_set_index]
        with open(cache_file, 'wb') as fid:
            cPickle.dump(gt_roidb, fid, cPickle.HIGHEST_PROTOCOL)
        print 'wrote gt roidb to {}'.format(cache_file)

        return gt_roidb

    def load_annotation(self, index):
        """
        for a given index, load image and bounding boxes info from XML file
        :param image_name: image name in the data dir
        :return: record['boxes', 'gt_classes', 'gt_overlaps', 'flipped']
        """
        # import xml.etree.ElementTree as ET
        roi_rec = dict()
        roi_rec['image'] = self.image_path_from_index(index)
        # roi_rec['image_name'] = 'img_' + index + '.jpg'

        # filename = os.path.join(self.data_path, 'labelTxt', os.path.splitext(os.path.basename(index))[0] + '.txt')
        img_path = self.image_path_from_index(index)
        w, h = Image.open(img_path).size
        roi_rec['height'] = float(h)
        roi_rec['width'] = float(w)

        #f = codecs.open(filename, 'r', 'utf-16')
        if self.image_set == 'train':
            filename = os.path.join(self.data_path, 'labelTxt', index + '.txt')
            f = codecs.open(filename, 'r')
            objs = f.readlines()
            objs = [obj.strip().split(' ') for obj in objs]
            # objs = tree.findall('object')
            if not self.config['use_diff']:
                non_diff_objs = [obj for obj in objs if obj[9] != '1']
                objs = non_diff_objs
            num_objs = len(objs)

            boxes = np.zeros((num_objs, 4), dtype=np.int16)
            gt_classes = np.zeros((num_objs), dtype=np.int32)
            overlaps = np.zeros((num_objs, self.num_classes), dtype=np.float32)

            class_to_index = dict(zip(self.classes, range(self.num_classes)))
            # Load object bounding boxes into a data frame.
            for ix, obj in enumerate(objs):
                bbox = obj
                # Make pixel indexes 0-based
                x1 = float(bbox[0]) - 1
                y1 = float(bbox[1]) - 1
                x2 = float(bbox[2]) - 1
                y2 = float(bbox[3]) - 1
                x3 = float(bbox[4]) - 1
                y3 = float(bbox[5]) - 1
                x4 = float(bbox[6]) - 1
                y4 = float(bbox[7]) - 1
                xmin = max(min(x1, x2, x3, x4), 0)
                xmax = max(x1, x2, x3, x4)
                ymin = max(min(y1, y2, y3, y4), 0)
                ymax = max(y1, y2, y3, y4)


                ## restric to (0, w) (0, h)
                xmin = min(max(xmin, 0), w - 1)
                xmax = min(max(xmax, 0), w - 1)
                ymin = min(max(ymin, 0), h - 1)
                ymax = min(max(ymax, 0), h - 1)
                cls = class_to_index[obj[8].lower().strip()]
                boxes[ix, :] = [xmin, ymin, xmax, ymax]
                gt_classes[ix] = cls
                overlaps[ix, cls] = 1.0
            roi_rec.update({'boxes': boxes,
                            'gt_classes': gt_classes,
                            'gt_overlaps': overlaps,
                            'max_classes': overlaps.argmax(axis=1),
                            'max_overlaps': overlaps.max(axis=1),
                            'flipped': False})
        return roi_rec

    def evaluate_detections(self, detections):
        """
        :param detections: [cls][image] = N x [x1, y1, x2, y2, x3, y3, x4, y4, score]
        :return:
        """
        detection_results_path = os.path.join(self.result_path, 'test_results')
        info = ''
        if not os.path.isdir(detection_results_path):
            os.mkdir(detection_results_path)
        self.write_DOTA_results(detections, threshold=0.0)
        return info

    def write_DOTA_results(self, all_boxes, threshold=0.2):
        """
        write results files in pascal devkit path
        :param all_boxes: boxes to be processed [bbox, confidence]
        :return: None
        """
        path = os.path.join(self.result_path, 'test_results')
        if os.path.isdir(path):
            print "delete original test results files!"
            os.system("rm -r {}".format(path))
            os.mkdir(path)
        for cls_ind, cls in enumerate(self.classes):
            if cls == '__background__':
                continue
            for im_ind, index in enumerate(self.image_set_index):
                dets = all_boxes[cls_ind][im_ind]
                # if dets.shape[0] == 0:
                #     print "no detection results in {}".format(index)
                # f = open(os.path.join(self.result_path, 'test_results', 'res_{}'.format(os.path.splitext(os.path.basename(index))[0] + '.txt')), 'a')
                f = open(os.path.join(self.result_path, 'test_results', '{}'.format(index + '.txt')), 'a')
                # the VOCdevkit expects 1-based indices
                for k in range(dets.shape[0]):
                    if dets[k, 4] <= threshold:
                        continue
                    f.write('{} {} {} {} {} {}\n'.format(int(dets[k, 0]), int(dets[k, 1]), int(dets[k, 2]),
                                                                     int(dets[k, 3]),dets[k, 4],self.classes[cls_ind]))
                    # f.write('{} {} {} {} {} {} {} {} {} {}\n'.format(int(dets[k, 0]), int(dets[k, 1]),
                    #                                                  int(dets[k, 2]), int(dets[k, 1]),
                    #                                                  int(dets[k, 2]), int(dets[k, 3]),
                    #                                                  int(dets[k, 0]), int(dets[k, 3]),
                    #                                                  dets[k, 4], self.classes[cls_ind]))

# DOTA_oriented contains 8 coordinates, so we have to do data dealing
class DOTA_oriented(IMDB):
    def __init__(self, image_set, root_path, data_path, result_path=None, mask_size=-1, binary_thresh=None):
        """
        fill basic information to initialize imdb
        :param image_set: train, test etc.
        :param root_path: 'selective_search_data' and 'cache'
        :param data_path: data and results
        :return: imdb object
        """
        self.image_set = image_set
        super(DOTA_oriented, self).__init__('DOTA_oriented', self.image_set, root_path, data_path, result_path)  # set self.name

        self.root_path = root_path
        self.data_path = data_path

        self.classes = ['__background__',  # always index 0
                        'plane', 'baseball-diamond',
                        'bridge', 'ground-track-field',
                        'small-vehicle', 'large-vehicle',
                        'ship', 'tennis-court',
                        'basketball-court', 'storage-tank',
                        'soccer-ball-field', 'roundabout',
                        'harbor', 'swimming-pool',
                        'helicopter']
        ## check it, if it is better for baseball-diamond
        self.angle_agnostic_classes = ['bridge',
                                       'ground-track-field', 'tennis-court',
                                       'basketball-court', 'storage-tank',
                                       'soccer-ball-field', 'roundabout',
                                       'swimming-pool']
        self.num_classes = len(self.classes)
        self.image_set_index = self.load_image_set_index()
        self.num_images = len(self.image_set_index)
        print 'num_images', self.num_images
        self.mask_size = mask_size
        self.binary_thresh = binary_thresh

        self.config = {'comp_id': 'comp4',
                       'use_diff': False,
                       'min_size': 2}

    def load_image_set_index(self):
        """
        find out which indexes correspond to given image set (train or val)
        :return:
        """
        image_set_index_file = os.path.join(self.data_path, self.image_set + '.txt')
        assert os.path.exists(image_set_index_file), 'Path does not exist: {}'.format(image_set_index_file)
        with open(image_set_index_file, 'r') as f:
            lines = f.readlines()
        image_lists = [line.strip() for line in lines]
        #image_lists = [os.path.join(self.data_path, 'images', line.strip() + '.jpg') for line in lines]
        return image_lists

    def image_path_from_index(self, index):
        """
        given image index, find out full path
        :param image_name: image name in the data dir
        :return: full path of this image
        """
        # hint: self.image_set means 'train' or 'test'
        # TODO: when data ready, the entrance here should be changed
        # image_file = os.path.join(self.data_path, self.image_set, index)
        image_file = os.path.join(self.data_path, 'images', index + '.png')
        assert os.path.exists(image_file), 'Path does not exist: {}'.format(image_file)
        return image_file

    def gt_roidb(self):
        """
        return ground truth image regions database
        :return: imdb[image_index]['boxes', 'gt_classes', 'gt_overlaps', 'flipped']
        """
        cache_file = os.path.join(self.cache_path, self.name + '_gt_roidb.pkl')
        if os.path.exists(cache_file):
            with open(cache_file, 'rb') as fid:
                roidb = cPickle.load(fid)
            print '{} gt roidb loaded from {}'.format(self.name, cache_file)
            return roidb

        # gt_roidb = [self.load_annotation(index) for index in self.image_set_index]

        # TODO: for debug
        gt_roidb = []
        count = 0
        for index in self.image_set_index:
            count += 1
            print count, '/', len(self.image_set_index)
            gt_roidb.append(self.load_annotation(index))
        with open(cache_file, 'wb') as fid:
            cPickle.dump(gt_roidb, fid, cPickle.HIGHEST_PROTOCOL)
        print 'wrote gt roidb to {}'.format(cache_file)

        return gt_roidb

    def load_annotation(self, index):
        """
        for a given index, load image and bounding boxes info from XML file
        :param image_name: image name in the data dir
        :return: record['boxes', 'gt_classes', 'gt_overlaps', 'flipped']
        """
        # import xml.etree.ElementTree as ET
        roi_rec = dict()
        roi_rec['image'] = self.image_path_from_index(index)
        # roi_rec['image_name'] = 'img_' + index + '.jpg'

        # filename = os.path.join(self.data_path, 'labelTxt', os.path.splitext(os.path.basename(index))[0] + '.txt')
        # tree = ET.parse(filename)
        img_path = self.image_path_from_index(index)
        w, h = Image.open(img_path).size
        # size = tree.find('size')
        roi_rec['height'] = float(h)
        roi_rec['width'] = float(w)

        valid_objs = []
        # f = codecs.open(filename, 'r', 'utf-16')
        if self.image_set == 'train':
            filename = os.path.join(self.data_path, 'labelTxt', index + '.txt')
            f = codecs.open(filename, 'r')
            objs = f.readlines()
            objs = [obj.strip().split(' ') for obj in objs]
            # objs = tree.findall('object')
            # if not self.config['use_diff']:
            #     non_diff_objs = [obj for obj in objs if obj[9] != '1']
            #     objs = non_diff_objs
            if not self.config['use_diff']:
                non_diff_objs = [obj for obj in objs if obj[9] == '0']
                objs = non_diff_objs
            # Load object bounding boxes into a data frame.
            for ix, obj in enumerate(objs):
                bbox = obj
                # Make pixel indexes 0-based
                # x1 = float(bbox[0]) - 1
                # y1 = float(bbox[1]) - 1
                # x2 = float(bbox[2]) - 1
                # y2 = float(bbox[3]) - 1
                # x3 = float(bbox[4]) - 1
                # y3 = float(bbox[5]) - 1
                # x4 = float(bbox[6]) - 1
                # y4 = float(bbox[7]) - 1

                x1 = min(max(float(bbox[0]), 0), w - 1)
                y1 = min(max(float(bbox[1]), 0), h - 1)
                x2 = min(max(float(bbox[2]), 0), w - 1)
                y2 = min(max(float(bbox[3]), 0), h - 1)
                x3 = min(max(float(bbox[4]), 0), w - 1)
                y3 = min(max(float(bbox[5]), 0), h - 1)
                x4 = min(max(float(bbox[6]), 0), w - 1)
                y4 = min(max(float(bbox[7]), 0), h - 1)
                # xmin = min(x1, x2, x3, x4)
                # xmax = max(x1, x2, x3, x4)
                # ymin = min(y1, y2, y3, y4)
                # ymax = max(y1, y2, y3, y4)

                # TODO: filter small instances
                xmin = max(min(x1, x2, x3, x4), 0)
                xmax = max(x1, x2, x3, x4)
                ymin = max(min(y1, y2, y3, y4), 0)
                ymax = max(y1, y2, y3, y4)

                # if xmax > xmin and ymax > ymin:
                #     obj[:8] = [x1, y1, x2, y2, x3, y3, x4, y4]
                #     valid_objs.append(obj)

                if ((xmax - xmin) > 10) and ((ymax - ymin) > 10):
                    obj[:8] = [x1, y1, x2, y2, x3, y3, x4, y4]
                    valid_objs.append(obj)

            objs = valid_objs
            num_objs = len(objs)
            boxes = np.zeros((num_objs, 8), dtype=np.uint16)
            gt_classes = np.zeros((num_objs), dtype=np.int32)
            overlaps = np.zeros((num_objs, self.num_classes), dtype=np.float32)
            class_to_index = dict(zip(self.classes, range(self.num_classes)))
            # TODO: test it
            for ix, obj in enumerate(objs):
                cls = class_to_index[obj[8].lower().strip()]
                if obj[8].lower().strip() in self.angle_agnostic_classes:
                    # if angle_agnostic, use choose_best_point,
                    # TODO: make the long side and short side check, choose the short side's top left as the first point
                    boxes[ix, :] = get_best_begin_point_wrapp(obj[:8])
                else:
                    boxes[ix, :] = obj[:8]
                gt_classes[ix] = cls
                overlaps[ix, cls] = 1.0

            roi_rec.update({'boxes': boxes,
                            'gt_classes': gt_classes,
                            'gt_overlaps': overlaps,
                            'max_classes': overlaps.argmax(axis=1),
                            'max_overlaps': overlaps.max(axis=1),
                            'flipped': False})
        return roi_rec

    def evaluate_detections(self, detections, ignore_cache):
        """
        :param detections: [cls][image] = N x [x1, y1, x2, y2, x3, y3, x4, y4, score]
        :return:
        """
        detection_results_path = os.path.join(self.result_path, 'test_results')
        info = ''
        if not os.path.isdir(detection_results_path):
            os.mkdir(detection_results_path)

        if ignore_cache:
            self.write_DOTA_results(detections, threshold=0.001)
            # pdb.set_trace()
        self.write_DOTA_results_comp4(detections, threshold=0.001)

        return info

    def draw_gt_and_detections(self, detections, thresh=0.2):
        # gt_folder = os.path.join(self.result_path, 'gt_on_image')
        det_folder = os.path.join(self.result_path, 'det_on_image')
        # if not os.path.isdir(gt_folder):
        #     os.mkdir(gt_folder)
        self.write_DOTA_results(detections, threshold=0.1)
        if not os.path.isdir(det_folder):
            os.mkdir(det_folder)
        for im_ind, index in enumerate(self.image_set_index):
            img_path = self.image_path_from_index(index)
            gt_db = self.load_annotation(index)
            gt_boxes = gt_db['boxes']
            det_path = os.path.join(self.result_path, 'test_results', 'res_{}'.format(os.path.splitext(os.path.basename(index))[0] + '.txt'))
            f = open(det_path, 'r')
            det_boxes_results = f.readlines()
            det_boxes = []
            for result in  det_boxes_results:
                result = result.strip().split(',')
                det_boxes.append([int(result[0]), int(result[1]), int(result[2]),int(result[3]),int(result[4]),int(result[5]),int(result[6]),int(result[7]),
                                  float(result[8]),result[9]])
            # det_boxes = detections[cls_ind][im_ind]
            det_boxes = np.array(det_boxes)
            img = cv2.imread(img_path)
            img_height, img_width = img.shape[0], img.shape[1]
            # original_img = img.copy()
            for k in range(gt_boxes.shape[0]):
                bbox = gt_boxes[k, :8]
                bbox = map(int, bbox)
                color = (0, 255, 0)
                xmax = max(bbox[0], bbox[2], bbox[4], bbox[6])
                ymax = max(bbox[1], bbox[3], bbox[5], bbox[7])
                if xmax > img_width:
                    print "extreme xmax", xmax
                if ymax > img_height:
                    print "extreme ymax", ymax
                for i in range(3):
                    cv2.line(img, (bbox[i * 2], bbox[i * 2 + 1]), (bbox[(i + 1) * 2], bbox[(i + 1) * 2 + 1]),
                             color=color, thickness=1)
                cv2.line(img, (bbox[6], bbox[7]), (bbox[0], bbox[1]), color=color, thickness=1)
            # cv2.imwrite(os.path.join(gt_folder, 'img_{}.jpg'.format(index)), img)
            # img = original_img
            for k in range(det_boxes.shape[0]):
                bbox = det_boxes[k, :8]
                score = det_boxes[k, 8]
                cls = det_boxes[k, 9]
                if score < thresh:
                    continue
                bbox = map(int, bbox)
                color = (0, 255, 255)
                for i in range(3):
                    cv2.line(img, (bbox[i * 2], bbox[i * 2 + 1]), (bbox[(i + 1) * 2], bbox[(i + 1) * 2 + 1]),
                             color=color, thickness=1)
                cv2.line(img, (bbox[6], bbox[7]), (bbox[0], bbox[1]), color=color, thickness=1)
                cv2.putText(img, '{} {}'.format(cls, score), (bbox[0], bbox[1] + 10),
                            color=(255, 255, 255), fontFace=cv2.FONT_HERSHEY_COMPLEX, fontScale=0.5)
            print os.path.join(det_folder, os.path.basename(index))
            cv2.imwrite(os.path.join(det_folder, os.path.basename(index)), img)


    def validate_clockwise_points(self, points):
        """
        Validates that the points that the 4 points that dlimite a polygon are in clockwise order.
        """

        if len(points) != 8:
            raise Exception("Points list not valid." + str(len(points)))

        point = [
            [int(points[0]), int(points[1])],
            [int(points[2]), int(points[3])],
            [int(points[4]), int(points[5])],
            [int(points[6]), int(points[7])]
        ]
        edge = [
            (point[1][0] - point[0][0]) * (point[1][1] + point[0][1]),
            (point[2][0] - point[1][0]) * (point[2][1] + point[1][1]),
            (point[3][0] - point[2][0]) * (point[3][1] + point[2][1]),
            (point[0][0] - point[3][0]) * (point[0][1] + point[3][1])
        ]

        summatory = edge[0] + edge[1] + edge[2] + edge[3];
        if summatory > 0:
            return False
        else:
            return True
    # TODO: test it
    def write_DOTA_results_comp4(self, all_boxes, threshold=0.002):
        """
        write results file in comp4 format
        :param all_boxes: boxes to be processed [bbox, confidence]
        :param threshold: None
        :return:
        """
        path = os.path.join(self.result_path, 'Task1_results')
        if os.path.isdir(path):
            print "delete original test results files!"
            os.system("rm -rf {}".format(path))
            os.mkdir(path)
        # pdb.set_trace()
        for cls_ind, cls in enumerate(self.classes):
            # pdb.set_trace()
            if cls == '__background__':
                continue
            if not os.path.exists(path):
                os.mkdir(path)
            with open(os.path.join(path, 'Task1_' + cls + '.txt'), 'w') as f_out:
                for im_ind, index in enumerate(self.image_set_index):
                    try:
                        dets = all_boxes[cls_ind][im_ind]
                    except:
                        print 'cls_ind:', cls_ind
                        print 'im_ind:', im_ind
                        return
                    else:
                        for k in range(dets.shape[0]):
                            if dets[k, 8] <= threshold:
                                continue
                            xmin = min(dets[k, 0], dets[k, 2], dets[k, 4], dets[k, 6])
                            xmax = max(dets[k, 0], dets[k, 2], dets[k, 4], dets[k, 6])
                            ymin = min(dets[k, 1], dets[k, 3], dets[k, 5], dets[k, 7])
                            ymax = max(dets[k, 1], dets[k, 3], dets[k, 5], dets[k, 7])
                            w = xmax - xmin
                            h = ymax - ymin
                            if (w * h < 10 * 10):
                                continue
                            if self.validate_clockwise_points(dets[k, 0:8]):
                                f_out.write('{} {} {} {} {} {} {} {} {} {}\n'.format(index, dets[k, 8],
                                                                                 int(dets[k, 0]), int(dets[k, 1]),
                                                                                 int(dets[k, 2]),
                                                                                 int(dets[k, 3]),
                                                                                 int(dets[k, 4]), int(dets[k, 5]),
                                                                                 int(dets[k, 6]),
                                                                                 int(dets[k, 7])
                                                                                 ))
                            else:
                                # print 'A detected box is anti-clockwise! Index:{}'.format(index)
                                # print dets[k, 0:8]
                                pass
        # pdb.set_trace()
        # TODO: change the hard code here
        nms_path = path + '_0.1_nms'
        if not os.path.exists(nms_path):
            os.mkdir(nms_path)
        mergebypoly(path, nms_path)
    def write_DOTA_results(self, all_boxes, threshold=0.02):
        """
        write results files in pascal devkit path
        :param all_boxes: boxes to be processed [bbox, confidence]
        :return: None
        """
        path = os.path.join(self.result_path, 'test_results')
        if os.path.isdir(path):
            print "delete original test results files!"
            os.system("rm -r {}".format(path))
            os.mkdir(path)
        for cls_ind, cls in enumerate(self.classes):
            if cls == '__background__':
                continue
            for im_ind, index in enumerate(self.image_set_index):
                # dets = all_boxes[cls_ind][im_ind]
                try:
                    dets = all_boxes[cls_ind][im_ind]
                except:
                    print 'cls_ind:', cls_ind
                    print 'im_ind:', im_ind
                    return
                else:
                    # if dets.shape[0] == 0:
                    #     print "no detection results in {}".format(index)
                    if not os.path.exists(os.path.join(self.result_path, 'test_results')):
                        os.mkdir(os.path.join(self.result_path, 'test_results'))
                    # f = open(os.path.join(self.result_path, 'test_results', 'res_{}'.format(os.path.splitext(os.path.basename(index))[0] + '.txt')), 'a')
                    f = open(os.path.join(self.result_path, 'test_results', '{}'.format(index + '.txt')), 'a')

                    # the VOCdevkit expects 1-based indices
                    for k in range(dets.shape[0]):
                        if dets[k, 8] <= threshold:
                            continue
                        if self.validate_clockwise_points(dets[k, 0:8]):
                            f.write('{} {} {} {} {} {} {} {} {} {}\n'.format(int(dets[k, 0]), int(dets[k, 1]), int(dets[k, 2]),
                                                                         int(dets[k, 3]),
                                                                         int(dets[k, 4]), int(dets[k, 5]), int(dets[k, 6]),
                                                                         int(dets[k, 7]), dets[k, 8],
                                                                         self.classes[cls_ind]))
                        else:
                           # print 'A detected box is anti-clockwise! Index:{}'.format(index)
                           # print dets[k, 0:8]
                            pass

class DOTA_oriented_v2(IMDB):
    def __init__(self, image_set, root_path, data_path, result_path=None, mask_size=-1, binary_thresh=None):
        """
        fill basic information to initialize imdb
        :param image_set: train, test etc.
        :param root_path: 'selective_search_data' and 'cache'
        :param data_path: data and results
        :return: imdb object
        """
        self.image_set = image_set
        super(DOTA_oriented_v2, self).__init__('DOTA_oriented_v2', self.image_set, root_path, data_path, result_path)  # set self.name

        self.root_path = root_path
        self.data_path = data_path

        self.classes = ['__background__',  # always index 0
                        'plane', 'baseball-diamond',
                        'bridge', 'ground-track-field',
                        'small-vehicle', 'large-vehicle',
                        'ship', 'tennis-court',
                        'basketball-court', 'storage-tank',
                        'soccer-ball-field', 'roundabout',
                        'harbor', 'swimming-pool',
                        'helicopter']
        ## check it, if it is better for baseball-diamond
        self.angle_agnostic_classes = [ 'plane', 'baseball-diamond',
                        'bridge', 'ground-track-field',
                        'small-vehicle', 'large-vehicle',
                        'ship', 'tennis-court',
                        'basketball-court', 'storage-tank',
                        'soccer-ball-field', 'roundabout',
                        'harbor', 'swimming-pool',
                        'helicopter']
        self.num_classes = len(self.classes)
        self.image_set_index = self.load_image_set_index()
        self.num_images = len(self.image_set_index)
        print 'num_images', self.num_images
        self.mask_size = mask_size
        self.binary_thresh = binary_thresh

        self.config = {'comp_id': 'comp4',
                       'use_diff': False,
                       'min_size': 2}

    def load_image_set_index(self):
        """
        find out which indexes correspond to given image set (train or val)
        :return:
        """
        image_set_index_file = os.path.join(self.data_path, self.image_set + '.txt')
        assert os.path.exists(image_set_index_file), 'Path does not exist: {}'.format(image_set_index_file)
        with open(image_set_index_file, 'r') as f:
            lines = f.readlines()
        image_lists = [line.strip() for line in lines]
        #image_lists = [os.path.join(self.data_path, 'images', line.strip() + '.jpg') for line in lines]
        return image_lists

    def image_path_from_index(self, index):
        """
        given image index, find out full path
        :param image_name: image name in the data dir
        :return: full path of this image
        """
        # hint: self.image_set means 'train' or 'test'
        # TODO: when data ready, the entrance here should be changed
        # image_file = os.path.join(self.data_path, self.image_set, index)
        image_file = os.path.join(self.data_path, 'images', index + '.png')
        assert os.path.exists(image_file), 'Path does not exist: {}'.format(image_file)
        return image_file

    def gt_roidb(self):
        """
        return ground truth image regions database
        :return: imdb[image_index]['boxes', 'gt_classes', 'gt_overlaps', 'flipped']
        """
        cache_file = os.path.join(self.cache_path, self.name + '_gt_roidb.pkl')
        if os.path.exists(cache_file):
            with open(cache_file, 'rb') as fid:
                roidb = cPickle.load(fid)
            print '{} gt roidb loaded from {}'.format(self.name, cache_file)
            return roidb

        # gt_roidb = [self.load_annotation(index) for index in self.image_set_index]

        # TODO: for debug
        gt_roidb = []
        count = 0
        for index in self.image_set_index:
            count += 1
            print count, '/', len(self.image_set_index)
            gt_roidb.append(self.load_annotation(index))
        with open(cache_file, 'wb') as fid:
            cPickle.dump(gt_roidb, fid, cPickle.HIGHEST_PROTOCOL)
        print 'wrote gt roidb to {}'.format(cache_file)

        return gt_roidb

    def load_annotation(self, index):
        """
        for a given index, load image and bounding boxes info from XML file
        :param image_name: image name in the data dir
        :return: record['boxes', 'gt_classes', 'gt_overlaps', 'flipped']
        """
        # import xml.etree.ElementTree as ET
        roi_rec = dict()
        roi_rec['image'] = self.image_path_from_index(index)
        # roi_rec['image_name'] = 'img_' + index + '.jpg'

        # filename = os.path.join(self.data_path, 'labelTxt', os.path.splitext(os.path.basename(index))[0] + '.txt')
        # tree = ET.parse(filename)
        img_path = self.image_path_from_index(index)
        w, h = Image.open(img_path).size
        # size = tree.find('size')
        roi_rec['height'] = float(h)
        roi_rec['width'] = float(w)

        valid_objs = []
        # f = codecs.open(filename, 'r', 'utf-16')
        if self.image_set == 'train':
            filename = os.path.join(self.data_path, 'labelTxt', index + '.txt')
            f = codecs.open(filename, 'r')
            objs = f.readlines()
            objs = [obj.strip().split(' ') for obj in objs]
            # objs = tree.findall('object')
            # if not self.config['use_diff']:
            #     non_diff_objs = [obj for obj in objs if obj[9] != '1']
            #     objs = non_diff_objs
            if not self.config['use_diff']:
                non_diff_objs = [obj for obj in objs if obj[9] == '0']
                objs = non_diff_objs
            # Load object bounding boxes into a data frame.
            for ix, obj in enumerate(objs):
                bbox = obj


                x1 = min(max(float(bbox[0]), 0), w - 1)
                y1 = min(max(float(bbox[1]), 0), h - 1)
                x2 = min(max(float(bbox[2]), 0), w - 1)
                y2 = min(max(float(bbox[3]), 0), h - 1)
                x3 = min(max(float(bbox[4]), 0), w - 1)
                y3 = min(max(float(bbox[5]), 0), h - 1)
                x4 = min(max(float(bbox[6]), 0), w - 1)
                y4 = min(max(float(bbox[7]), 0), h - 1)


                # TODO: filter small instances
                xmin = max(min(x1, x2, x3, x4), 0)
                xmax = max(x1, x2, x3, x4)
                ymin = max(min(y1, y2, y3, y4), 0)
                ymax = max(y1, y2, y3, y4)

                # if xmax > xmin and ymax > ymin:
                #     obj[:8] = [x1, y1, x2, y2, x3, y3, x4, y4]
                #     valid_objs.append(obj)

                if ((xmax - xmin) > 10) and ((ymax - ymin) > 10):
                    obj[:8] = [x1, y1, x2, y2, x3, y3, x4, y4]
                    valid_objs.append(obj)

            objs = valid_objs
            num_objs = len(objs)
            boxes = np.zeros((num_objs, 8), dtype=np.uint16)
            gt_classes = np.zeros((num_objs), dtype=np.int32)
            overlaps = np.zeros((num_objs, self.num_classes), dtype=np.float32)
            class_to_index = dict(zip(self.classes, range(self.num_classes)))
            # TODO: test it
            for ix, obj in enumerate(objs):
                cls = class_to_index[obj[8].lower().strip()]
                if obj[8].lower().strip() in self.angle_agnostic_classes:
                    # if angle_agnostic, use choose_best_point,
                    # TODO: make the long side and short side check, choose the short side's top left as the first point
                    boxes[ix, :] = get_best_begin_point_wrapp(obj[:8])
                else:
                    boxes[ix, :] = obj[:8]
                gt_classes[ix] = cls
                overlaps[ix, cls] = 1.0

            roi_rec.update({'boxes': boxes,
                            'gt_classes': gt_classes,
                            'gt_overlaps': overlaps,
                            'max_classes': overlaps.argmax(axis=1),
                            'max_overlaps': overlaps.max(axis=1),
                            'flipped': False})
        return roi_rec

    def evaluate_detections(self, detections, ignore_cache):
        """
        :param detections: [cls][image] = N x [x1, y1, x2, y2, x3, y3, x4, y4, score]
        :return:
        """
        detection_results_path = os.path.join(self.result_path, 'test_results')
        info = ''
        if not os.path.isdir(detection_results_path):
            os.mkdir(detection_results_path)

        # if ignore_cache:
        self.write_DOTA_results(detections, threshold=0.001)
        # pdb.set_trace()
        self.write_DOTA_results_comp4(detections, threshold=0.001)

        return info

    def draw_gt_and_detections(self, detections, thresh=0.2):
        # gt_folder = os.path.join(self.result_path, 'gt_on_image')
        det_folder = os.path.join(self.result_path, 'det_on_image')
        # if not os.path.isdir(gt_folder):
        #     os.mkdir(gt_folder)
        self.write_DOTA_results(detections, threshold=0.1)
        if not os.path.isdir(det_folder):
            os.mkdir(det_folder)
        for im_ind, index in enumerate(self.image_set_index):
            img_path = self.image_path_from_index(index)
            gt_db = self.load_annotation(index)
            gt_boxes = gt_db['boxes']
            det_path = os.path.join(self.result_path, 'test_results', 'res_{}'.format(os.path.splitext(os.path.basename(index))[0] + '.txt'))
            f = open(det_path, 'r')
            det_boxes_results = f.readlines()
            det_boxes = []
            for result in  det_boxes_results:
                result = result.strip().split(',')
                det_boxes.append([int(result[0]), int(result[1]), int(result[2]),int(result[3]),int(result[4]),int(result[5]),int(result[6]),int(result[7]),
                                  float(result[8]),result[9]])
            # det_boxes = detections[cls_ind][im_ind]
            det_boxes = np.array(det_boxes)
            img = cv2.imread(img_path)
            img_height, img_width = img.shape[0], img.shape[1]
            # original_img = img.copy()
            for k in range(gt_boxes.shape[0]):
                bbox = gt_boxes[k, :8]
                bbox = map(int, bbox)
                color = (0, 255, 0)
                xmax = max(bbox[0], bbox[2], bbox[4], bbox[6])
                ymax = max(bbox[1], bbox[3], bbox[5], bbox[7])
                if xmax > img_width:
                    print "extreme xmax", xmax
                if ymax > img_height:
                    print "extreme ymax", ymax
                for i in range(3):
                    cv2.line(img, (bbox[i * 2], bbox[i * 2 + 1]), (bbox[(i + 1) * 2], bbox[(i + 1) * 2 + 1]),
                             color=color, thickness=1)
                cv2.line(img, (bbox[6], bbox[7]), (bbox[0], bbox[1]), color=color, thickness=1)
            # cv2.imwrite(os.path.join(gt_folder, 'img_{}.jpg'.format(index)), img)
            # img = original_img
            for k in range(det_boxes.shape[0]):
                bbox = det_boxes[k, :8]
                score = det_boxes[k, 8]
                cls = det_boxes[k, 9]
                if score < thresh:
                    continue
                bbox = map(int, bbox)
                color = (0, 255, 255)
                for i in range(3):
                    cv2.line(img, (bbox[i * 2], bbox[i * 2 + 1]), (bbox[(i + 1) * 2], bbox[(i + 1) * 2 + 1]),
                             color=color, thickness=1)
                cv2.line(img, (bbox[6], bbox[7]), (bbox[0], bbox[1]), color=color, thickness=1)
                cv2.putText(img, '{} {}'.format(cls, score), (bbox[0], bbox[1] + 10),
                            color=(255, 255, 255), fontFace=cv2.FONT_HERSHEY_COMPLEX, fontScale=0.5)
            print os.path.join(det_folder, os.path.basename(index))
            cv2.imwrite(os.path.join(det_folder, os.path.basename(index)), img)

    def validate_clockwise_points(self, points):
        """
        Validates that the points that the 4 points that dlimite a polygon are in clockwise order.
        """

        if len(points) != 8:
            raise Exception("Points list not valid." + str(len(points)))

        point = [
            [int(points[0]), int(points[1])],
            [int(points[2]), int(points[3])],
            [int(points[4]), int(points[5])],
            [int(points[6]), int(points[7])]
        ]
        edge = [
            (point[1][0] - point[0][0]) * (point[1][1] + point[0][1]),
            (point[2][0] - point[1][0]) * (point[2][1] + point[1][1]),
            (point[3][0] - point[2][0]) * (point[3][1] + point[2][1]),
            (point[0][0] - point[3][0]) * (point[0][1] + point[3][1])
        ]

        summatory = edge[0] + edge[1] + edge[2] + edge[3];
        if summatory > 0:
            return False
        else:
            return True
    # TODO: test it
    def write_DOTA_results_comp4(self, all_boxes, threshold=0.002):
        """
        write results file in comp4 format
        :param all_boxes: boxes to be processed [bbox, confidence]
        :param threshold: None
        :return:
        """
        path = os.path.join(self.result_path, 'Task1_results')
        if os.path.isdir(path):
            print "delete original test results files!"
            os.system("rm -rf {}".format(path))
            os.mkdir(path)
        # pdb.set_trace()
        for cls_ind, cls in enumerate(self.classes):
            # pdb.set_trace()
            if cls == '__background__':
                continue
            if not os.path.exists(path):
                os.mkdir(path)
            with open(os.path.join(path, 'Task1_' + cls + '.txt'), 'w') as f_out:
                for im_ind, index in enumerate(self.image_set_index):
                    try:
                        dets = all_boxes[cls_ind][im_ind]
                    except:
                        print 'cls_ind:', cls_ind
                        print 'im_ind:', im_ind
                        return
                    else:
                        for k in range(dets.shape[0]):
                            if dets[k, 8] <= threshold:
                                continue
                            xmin = min(dets[k, 0], dets[k, 2], dets[k, 4], dets[k, 6])
                            xmax = max(dets[k, 0], dets[k, 2], dets[k, 4], dets[k, 6])
                            ymin = min(dets[k, 1], dets[k, 3], dets[k, 5], dets[k, 7])
                            ymax = max(dets[k, 1], dets[k, 3], dets[k, 5], dets[k, 7])
                            w = xmax - xmin
                            h = ymax - ymin
                            if (w * h < 10 * 10):
                                continue
                            if self.validate_clockwise_points(dets[k, 0:8]):
                                f_out.write('{} {} {} {} {} {} {} {} {} {}\n'.format(index, dets[k, 8],
                                                                                 int(dets[k, 0]), int(dets[k, 1]),
                                                                                 int(dets[k, 2]),
                                                                                 int(dets[k, 3]),
                                                                                 int(dets[k, 4]), int(dets[k, 5]),
                                                                                 int(dets[k, 6]),
                                                                                 int(dets[k, 7])
                                                                                 ))
                            else:
                                # print 'A detected box is anti-clockwise! Index:{}'.format(index)
                                # print dets[k, 0:8]
                                pass
        # pdb.set_trace()
        # TODO: change the hard code here
        nms_path = path + '_0.1_nms'
        if not os.path.exists(nms_path):
            os.mkdir(nms_path)
        mergebypoly(path, nms_path)
    def write_DOTA_results(self, all_boxes, threshold=0.02):
        """
        write results files in pascal devkit path
        :param all_boxes: boxes to be processed [bbox, confidence]
        :return: None
        """
        path = os.path.join(self.result_path, 'test_results')
        if os.path.isdir(path):
            print "delete original test results files!"
            os.system("rm -r {}".format(path))
            os.mkdir(path)
        for cls_ind, cls in enumerate(self.classes):
            if cls == '__background__':
                continue
            for im_ind, index in enumerate(self.image_set_index):
                # dets = all_boxes[cls_ind][im_ind]
                try:
                    dets = all_boxes[cls_ind][im_ind]
                except:
                    print 'cls_ind:', cls_ind
                    print 'im_ind:', im_ind
                    return
                else:
                    # if dets.shape[0] == 0:
                    #     print "no detection results in {}".format(index)
                    if not os.path.exists(os.path.join(self.result_path, 'test_results')):
                        os.mkdir(os.path.join(self.result_path, 'test_results'))
                    # f = open(os.path.join(self.result_path, 'test_results', 'res_{}'.format(os.path.splitext(os.path.basename(index))[0] + '.txt')), 'a')
                    f = open(os.path.join(self.result_path, 'test_results', '{}'.format(index + '.txt')), 'a')

                    # the VOCdevkit expects 1-based indices
                    for k in range(dets.shape[0]):
                        if dets[k, 8] <= threshold:
                            continue
                        if self.validate_clockwise_points(dets[k, 0:8]):
                            f.write('{} {} {} {} {} {} {} {} {} {}\n'.format(int(dets[k, 0]), int(dets[k, 1]), int(dets[k, 2]),
                                                                         int(dets[k, 3]),
                                                                         int(dets[k, 4]), int(dets[k, 5]), int(dets[k, 6]),
                                                                         int(dets[k, 7]), dets[k, 8],
                                                                         self.classes[cls_ind]))
                        else:
                           # print 'A detected box is anti-clockwise! Index:{}'.format(index)
                           # print dets[k, 0:8]
                            pass