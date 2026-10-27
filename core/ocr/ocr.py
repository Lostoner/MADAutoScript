"""BAAS single-line candidates and 0.2 character filtering, with MAD ROI data."""
import re
from core.device.runtime import Coordinates
from core.exception import OcrInternalError

def filtered(result,filter_score=.2):
    return ''.join(c for c,s in zip(result['text'],result['char_scores']) if s>filter_score)

class Baas_ocr:
    def __init__(self,client): self.client=client
    def get_area_img(self,frame,area):
        image=frame.image if hasattr(frame,'image') else frame
        coordinates=Coordinates((image.shape[1],image.shape[0]))
        x1,y1,x2,y2=coordinates.raw_area(area)
        return image[y1:y2,x1:x2]
    def get_region_res(self,baas,region,language='zh-cn',candidates='',filter_score=.2,**kwargs):
        return self.ocr_for_single_line(language,origin_image=self.get_area_img(baas.latest_img_array,region),candidates=candidates,filter_score=filter_score)
    def ocr_for_single_line(self,language,origin_image=None,candidates='',filter_score=.2,**kwargs):
        result=self.client.single_line(origin_image,language,candidates)
        return filtered(result,filter_score)
    def recognize_int(self,baas,region,language='en-us',candidates='0123456789',default=0):
        text=self.get_region_res(baas,region,language,candidates)
        digits=''.join(c for c in text if c.isdigit())
        return int(digits) if digits else default
    def text_list(self,baas,region,language='zh-cn',candidates=''):
        raw=self.client.ocr(self.get_area_img(baas.latest_img_array,region),language,candidates)
        ratio=baas.latest_img_array.shape[1]/1280
        result=[]
        for item in raw['text_list']:
            text=filtered(item)
            if not text: continue
            points=[(x/ratio+region[0],y/ratio+region[1]) for x,y in item['position']]
            result.append({'text':re.sub(r'\s+','',text),'points':points,
                           'point':(sum(p[0] for p in points)/4,sum(p[1] for p in points)/4)})
        return result
