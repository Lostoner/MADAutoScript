"""MAD image/search adapter for BAAS image.py, GPL-3.0-only.

BAAS 1110e88df5955df277737ea9717869b9ca88362b. Preserve base ROI->raw
crop, INTER_AREA template resizing, normalized match and average BGR comparison.
"""
from dataclasses import dataclass
import cv2
import numpy as np
from core import position
from core.device.runtime import Coordinates,DeviceError

@dataclass
class ImageContext:
    latest_img_array: np.ndarray
    identifier: str=position.IDENTIFIER
    @property
    def ratio(self): return self.latest_img_array.shape[1]/1280

def screenshot_cut(context,area):
    image=context.latest_img_array
    x1,y1,x2,y2=Coordinates((image.shape[1],image.shape[0])).raw_area(area)
    return image[y1:y2,x1:x2,:]

def img_cut(image,area):
    x1,y1,x2,y2=area
    if not (0<=x1<x2<=image.shape[1] and 0<=y1<y2<=image.shape[0]):
        raise DeviceError('图像裁剪区域越界或为空。')
    return image[y1:y2,x1:x2]

def compare_rgb(rgb1,rgb2,rgb_diff):
    return bool(np.all(np.abs(np.asarray(rgb1)-np.asarray(rgb2))<=rgb_diff))

def compare_image_rgb(img1,img2,rgb_diff=20):
    if not img1.size or not img2.size:
        raise DeviceError('不能比较空图像。')
    return compare_rgb(np.mean(img1,axis=(0,1)),np.mean(img2,axis=(0,1)),rgb_diff)

def match_details(context,name,threshold=None,rgb_diff=None):
    position.init_image_data(context)
    info=position.metadata[context.identifier][name]
    template=position.image_dic[context.identifier][name]
    cropped=screenshot_cut(context,position.get_area(context.identifier,name))
    resized=cv2.resize(cropped,(template.shape[1],template.shape[0]),interpolation=cv2.INTER_AREA)
    score=float(cv2.matchTemplate(resized,template,cv2.TM_CCOEFF_NORMED)[0][0])
    threshold=info['threshold'] if threshold is None else threshold
    rgb_diff=info['rgb_diff'] if rgb_diff is None else rgb_diff
    difference=np.abs(np.mean(template,axis=(0,1))-np.mean(cropped,axis=(0,1)))
    return {'name':name,'matched':score>=threshold and bool(np.all(difference<=rgb_diff)),
        'score':score,'threshold':threshold,'mean_bgr_difference':difference.tolist(),
        'rgb_diff':rgb_diff,'base_area':info['base_area']}

def compare_image(context,name,threshold=None,rgb_diff=None):
    position.init_image_data(context)
    if name not in position.image_dic[context.identifier]: return False
    return match_details(context,name,threshold,rgb_diff)['matched']

def swipe_search_target_str(self,name=None,search_area=(0,0,1280,720),threshold=.8,
        possible_strs=None,target_str_index=0,swipe_params=(0,0,0,0,.3,1),ocr_language='zh-cn',
        ocr_region_offsets=(0,0,0,0),ocr_str_replace_func=None,max_swipe_times=3,
        ocr_candidates='',ocr_filter_score=.2,first_retry_dir=0,**kwargs):
    """BAAS candidate-index and alternating-direction search.

    MAD list rows are located by its text detector instead of BA's enter-button
    template; ordering, candidate matching, retry count and direction are retained.
    """
    target=possible_strs[target_str_index]
    direction=first_retry_dir
    reverse=(*swipe_params[2:4],*swipe_params[:2],*swipe_params[4:])
    normalise=ocr_str_replace_func or (lambda x:x)
    for attempt in range(max_swipe_times):
        if attempt: self.update_screenshot_array()
        rows=self.ocr.text_list(self,search_area,ocr_language,ocr_candidates)
        indexes=[]
        for row in rows:
            text=normalise(row['text'])
            if text==target: return row['point']
            if text in possible_strs: indexes.append(possible_strs.index(text))
        if indexes and target_str_index>max(indexes): params=swipe_params
        elif indexes and target_str_index<min(indexes): params=reverse
        else:
            params=swipe_params if direction==0 else reverse
            direction^=1
        self.swipe(*params)
    return None

def resize_ss_image(context,area,interpolation=cv2.INTER_AREA):
    return cv2.resize(screenshot_cut(context,area),(round(area[2]-area[0]),round(area[3]-area[1])),interpolation=interpolation)

def search_in_area(context,name,area=(0,0,1280,720),threshold=0.88,rgb_diff=22,ret_max_val=False):
    position.init_image_data(context)
    template=position.image_dic[context.identifier][name]
    image=resize_ss_image(context,area)
    if image.shape[0]<template.shape[0] or image.shape[1]<template.shape[1]:
        raise DeviceError('模板大于搜索区域。')
    scores=cv2.matchTemplate(image,template,cv2.TM_CCOEFF_NORMED)
    _,score,_,point=cv2.minMaxLoc(scores)
    crop=img_cut(image,(*point,point[0]+template.shape[1],point[1]+template.shape[0]))
    result=(point[0]+area[0],point[1]+area[1]) if score>=threshold and compare_image_rgb(template,crop,rgb_diff) else False
    return (result,float(score)) if ret_max_val else result
