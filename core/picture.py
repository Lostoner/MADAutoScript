"""BAAS co_detect, baseline 1110e88; only MAD feature/popup adapters differ."""
from __future__ import annotations
import time
import typing
from core import color, image
from core.color import match_rgb_feature
from core.exception import RequestHumanTakeOver, FunctionCallTimeout, PackageIncorrect

def co_detect(
    self: Baas_thread,
    rgb_ends: typing.Union[list[str], str] = None,
    rgb_reactions: dict = None,
    img_ends: typing.Union[list, str, tuple] = None,
    img_reactions: dict = None,
    skip_first_screenshot=False,
    tentative_click=False,
    tentative_x=1238,
    tentative_y=45,
    max_fail_cnt=10,
    pop_ups_rgb_reactions: dict = None,
    pop_ups_img_reactions: dict = None,
    time_out=600,
    check_pkg_interval=20
):
    """
        Detects specific RGB or image features on the screen and performs actions based on the detection.

        Args:
            self: The BAAS thread.
            rgb_ends (list, optional): RGB features that indicate the end of detection.
            rgb_reactions (dict, optional): Possible RGB features and their corresponding click positions.
            img_ends (list or str or tuple, optional): Image features that indicate the end of detection.
            img_reactions (dict, optional): Possible image features and their corresponding click positions.
            skip_first_screenshot (bool, optional): Whether to skip the first screenshot to save time.
            tentative_click (bool, optional): Whether to perform tentative clicks if detection fails.
            tentative_x (int, optional): X-coordinate for tentative clicks.
            tentative_y (int, optional): Y-coordinate for tentative clicks.
            max_fail_cnt (int, optional): The count of recognition failures before performing a tentative click.
            pop_ups_rgb_reactions (dict, optional): Possible RGB features for pop-ups and their corresponding click positions.
            pop_ups_img_reactions (dict, optional): Possible image features for pop-ups and their corresponding click positions.
            time_out (int, optional): Timeout(second(s)) for the detection process.
            check_pkg_interval (int, optional): Interval(second(s)) for checking the current package.

        Raises:
            FunctionCallTimeout: If the detection process times out.
            PackageIncorrect: If the current package is incorrect.
            RequestHumanTakeOver: If the detection process is stopped manually.

        Returns:
            str: The name of the detected end feature.
    """

    # Initialize variables
    fail_cnt = 0
    self.last_click_time = 0
    self.last_click_position = (0, 0)
    self.last_click_name = ""
    start_time = time.time()
    feature_last_appear_time = start_time
    last_check_pkg_time = start_time

    # Convert single RGB or image features to lists
    if type(rgb_ends) is not list:
        rgb_ends = [rgb_ends]
    if type(img_ends) is not list:
        img_ends = [img_ends]

    while self.flag_run:
        current_time = time.time()
        if skip_first_screenshot:
            skip_first_screenshot = False
        else:
            self.update_screenshot_array()
        # time out check
        if current_time - start_time > time_out:
            raise FunctionCallTimeout("Co_detect function timeout reached.")

        # package check
        if self.is_android_device:
            if (current_time - feature_last_appear_time > check_pkg_interval
                and current_time - last_check_pkg_time > check_pkg_interval):
                last_check_pkg_time = current_time
                pkgName = self.connection.get_current_package()
                self.logger.info(f"Current package name: {pkgName}")
                if pkgName != self.package_name:
                    raise PackageIncorrect(pkgName)

        # loading check
        color.wait_loading(self)

        # exit the stage if any end feature is matched
        for rgb_feature in rgb_ends:
            if rgb_feature is None:
                continue
            if color.match_rgb_feature(self, rgb_feature):
                self.logger.info("Stage ended with matched RGB feature: " + rgb_feature)
                return rgb_feature
        for img_feature in img_ends:
            if img_feature is None:
                continue
            if match_img_feature(self, img_feature):
                self.logger.info('Stage ended with matched img feature: ' + str(img_feature))
                return img_feature

        # click if match reaction rules
        matched = False
        if rgb_reactions is not None:
            for rgb_feature, click in rgb_reactions.items():
                if match_rgb_feature(self, rgb_feature):
                    matched = True
                    feature_last_appear_time = current_time
                    if (current_time - self.last_click_time <= 2
                        and self.last_click_position[0] == click[0] and self.last_click_position[1] == click[1]
                        and self.last_click_name == rgb_feature):
                        # avoid duplicated clicks

                        break
                    self.logger.info(f"RGB feature: {rgb_feature} -> Click @ ({click[0]},{click[1]})")
                    if click[0] >= 0 and click[1] >= 0:
                        self.last_click_time = current_time
                        self.click(click[0], click[1])
                        self.last_click_position = (click[0], click[1])
                        self.last_click_name = rgb_feature
                    break
        if not matched and img_reactions is not None:
            for img_feature, click in img_reactions.items():
                threshold = 0.8 if len(click) < 3 else click[2]
                rgb_diff = 20 if len(click) < 4 else click[3]
                if match_img_feature(self, img_feature, threshold, rgb_diff):
                    matched = True
                    feature_last_appear_time = current_time
                    if (time.time() - self.last_click_time <= 2
                        and self.last_click_position[0] == click[0] and self.last_click_position[1] == click[1]
                        and self.last_click_name == img_feature):
                        break
                    self.logger.info(f"Image feature: {img_feature} -> Click @ ({click[0]},{click[1]})")
                    if click[0] >= 0 and click[1] >= 0:
                        self.last_click_time = feature_last_appear_time
                        self.click(click[0], click[1])
                        self.last_click_position = (click[0], click[1])
                        self.last_click_name = img_feature
                    break
        if not matched and not deal_with_pop_ups(self, pop_ups_rgb_reactions, pop_ups_img_reactions):
            if tentative_click:
                fail_cnt += 1
                if fail_cnt > max_fail_cnt:
                    self.logger.info(
                        f"Performing tentative click @ ({tentative_x},{tentative_y}) due to recognition failure.")
                    self.click(tentative_x, tentative_y)

                    # if recognition failed for too many times, then preform a tentative click and take a break.
                    time.sleep(self.screenshot_interval * 5)
                    # fail_cnt = 0
        if matched:
            fail_cnt = 0

    if not self.flag_run:
        raise RequestHumanTakeOver("Request Human Take Over.")


def match_img_feature(self,feature,threshold=.8,rgb_diff=20):
    if isinstance(feature,tuple):
        feature,threshold,rgb_diff=(*feature,*[threshold,rgb_diff][len(feature)-1:])
    from core.mad_features import FEATURES
    if feature in FEATURES:
        return self.match(feature)
    return image.compare_image(self,feature,threshold,rgb_diff)

def match_any_img_feature(self,features):
    return any(match_img_feature(self,name) for name in features)

def deal_with_pop_ups(self,pop_ups_rgb_reactions=None,pop_ups_img_reactions=None):
    from module.restart import deal_with_popup
    for name,point in (pop_ups_rgb_reactions or {}).items():
        if color.match_rgb_feature(self,name):
            self.click(*point); return True
    for name,point in (pop_ups_img_reactions or {}).items():
        if match_img_feature(self,name):
            self.click(*point); return True
    return deal_with_popup(self)

GAME_ONE_TIME_POP_UPS={'MAD':{}}
