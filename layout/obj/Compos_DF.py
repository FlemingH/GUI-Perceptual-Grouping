import json
import pandas as pd
import numpy as np
import copy
import cv2
from random import randint as rint
from sklearn.cluster import DBSCAN

import layout.lib.repetition_recognition as rep
import layout.lib.draw as draw
import layout.lib.pairing as pairing


class ComposDF:
    def __init__(self, json_file=None, json_data=None, gui_img=None):
        self.json_file = json_file
        self.json_data = json_data if json_data is not None else json.load(open(self.json_file))
        self.compos_json = self.json_data['compos']
        self.compos_dataframe = self.cvt_json_to_df()
        self.img = gui_img

        self.item_id = 0    # id of list item

    def copy(self):
        return copy.deepcopy(self)

    def reload_compos(self, json_file=None):
        if json_file is None:
            json_file = self.json_file
        self.json_data = json.load(open(json_file))
        self.compos_json = self.json_data['compos']
        self.compos_dataframe = self.cvt_json_to_df()

    def cvt_json_to_df(self):
        df = pd.DataFrame(columns=['id', 'class', 'column_min', 'column_max', 'row_min', 'row_max',
                                   'height', 'width', 'area', 'center', 'center_column', 'center_row', 'text_content',
                                   'children', 'parent'])
        for i, compo in enumerate(self.compos_json):
            if 'clip_path' in compo:
                compo.pop('clip_path')
            if 'text_content' not in compo:
                compo['text_content'] = None
            if 'position' in compo:
                pos = compo['position']
                compo['column_min'], compo['column_max'] = int(pos['column_min']), int(pos['column_max'])
                compo['row_min'], compo['row_max'] = int(pos['row_min']), int(pos['row_max'])
                compo.pop('position')
            else:
                compo['column_min'], compo['column_max'] = int(compo['column_min']), int(compo['column_max'])
                compo['row_min'], compo['row_max'] = int(compo['row_min']), int(compo['row_max'])
            if 'children' not in compo or compo['children'] is None:
                compo['children'] = None
            else:
                compo['children'] = tuple(compo['children'])
            if 'parent' not in compo:
                compo['parent'] = None
            compo['height'], compo['width'] = int(compo['height']), int(compo['width'])
            compo['area'] = compo['height'] * compo['width']
            compo['center'] = ((compo['column_min'] + compo['column_max']) / 2, (compo['row_min'] + compo['row_max']) / 2)
            compo['center_column'] = compo['center'][0]
            compo['center_row'] = compo['center'][1]

            df.loc[i] = compo
        return df

    def to_csv(self, file):
        self.compos_dataframe.to_csv(file)

    '''
    ******************************
    *** Repetition Recognition ***
    ******************************
    '''
    def repetitive_block_recognition(self):
        '''
        Recognize repetitive layout of blocks that contains multiple elements in them
        '''
        df = self.compos_dataframe
        blocks = df[(df['class']=='Block') & (~pd.isna(df['children'])) & (df['children']!=-1)]
        children_list = []
        connections_list = []
        # calculate children connections in each block
        for i in range(len(blocks)):
            children = df[df['id'].isin(blocks.iloc[i]['children'])].sort_values('center_row')
            children_list.append(children)
            connections_list.append(rep.calc_connections(children))
        # match children connections
        start_pair_id = max(self.compos_dataframe['group_pair']) if 'group_pair' in self.compos_dataframe else 0
        paired_blocks = rep.recog_repetition_block_by_children_connections(children_list, connections_list, start_pair_id)

        # merge the pairing result into the original dataframe
        df_all = self.compos_dataframe
        if paired_blocks is not None:
            if 'group_pair' not in self.compos_dataframe:
                df_all = self.compos_dataframe.merge(paired_blocks, how='left')
            else:
                df_all.loc[df_all[df_all['id'].isin(paired_blocks['id'])]['id'], 'group_pair'] = paired_blocks['group_pair']
            df_all = df_all.fillna(-1)
            df_all['group_pair'] = df_all['group_pair'].astype(int)
        else:
            if 'group_pair' not in self.compos_dataframe:
                df_all['group_pair'] = -1
        self.compos_dataframe = df_all

    def repetitive_group_recognition(self, show=False, clean_attrs=True):
        '''
        Recognize repetitive layout of elements that are not contained in Block by clustering
        '''
        df_nontext = rep.recog_repetition_nontext(self, show, only_non_contained_compo=True)
        df_text = rep.recog_repetition_text(self, show, only_non_contained_compo=True)
        df = self.compos_dataframe

        df['alignment'] = np.nan
        if 'alignment' in df_nontext:
            df.loc[df['alignment'].isna(), 'alignment'] = df_nontext['alignment']
        df = df.merge(df_nontext, how='left')
        if 'alignment' in df_text:
            df.loc[df['alignment'].isna(), 'alignment'] = df_text['alignment']
        df = df.merge(df_text, how='left')
        df.rename({'alignment': 'alignment_in_group'}, axis=1, inplace=True)

        if clean_attrs:
            df = df.drop(list(df.filter(like='cluster')), axis=1)
            df = df.fillna(-1)

            for i in range(len(df)):
                if df.iloc[i]['group_nontext'] != -1:
                    df.loc[i, 'group'] = 'nt-' + str(int(df.iloc[i]['group_nontext']))
                elif df.iloc[i]['group_text'] != -1:
                    df.loc[i, 'group'] = 't-' + str(int(df.iloc[i]['group_text']))

            groups = df.groupby('group').groups
            for i in groups:
                if len(groups[i]) == 1:
                    df.loc[groups[i], 'group'] = -1
            df.group = df.group.fillna(-1)

        # df = rep.rm_invalid_groups(df)
        self.compos_dataframe = df

    def cluster_dbscan_by_attr(self, attr, eps, min_samples=1, show=True, show_method='line'):
        x = np.reshape(list(self.compos_dataframe[attr]), (-1, 1))
        clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(x)
        tag = 'cluster_' + attr
        self.compos_dataframe[tag] = clustering.labels_
        self.compos_dataframe[tag].astype(int)
        if show:
            if show_method == 'line':
                self.visualize(gather_attr=tag, name=tag)
            elif show_method == 'block':
                self.visualize_fill(gather_attr=tag, name=tag)

    def cluster_dbscan_by_attrs(self, attrs, eps, min_samples=1, show=True, show_method='line'):
        x = list(self.compos_dataframe[attrs].values)
        clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(x)
        tag = 'cluster_' + '_'.join(attrs)
        self.compos_dataframe[tag] = clustering.labels_
        self.compos_dataframe[tag].astype(int)
        if show:
            if show_method == 'line':
                self.visualize(gather_attr=tag, name=tag)
            elif show_method == 'block':
                self.visualize_fill(gather_attr=tag, name=tag)

    def group_by_clusters(self, cluster, alignment,
                          new_groups=True, show=True, show_method='block'):
        compos = self.compos_dataframe
        if 'group' not in compos.columns or new_groups:
            self.compos_dataframe['group'] = -1
            group_id = 0
        else:
            group_id = compos['group'].max() + 1

        groups = self.compos_dataframe.groupby(cluster).groups
        for i in groups:
            if len(groups[i]) > 1:
                self.compos_dataframe.loc[list(groups[i]), 'group'] = group_id
                self.compos_dataframe.loc[list(groups[i]), 'alignment'] = alignment
                group_id += 1
        self.compos_dataframe['group'].astype(int)

        if show:
            name = cluster if type(cluster) != list else '+'.join(cluster)
            if show_method == 'line':
                self.visualize(gather_attr='group', name=name)
            elif show_method == 'block':
                self.visualize_fill(gather_attr='group', name=name)

    def closer_group_by_mean_area(self, compo_index, group1, group2):
        compo = self.compos_dataframe.loc[compo_index]
        g1 = group1[group1['id'] != compo['id']]
        g2 = group2[group2['id'] != compo['id']]
        # if len(cl2) == 1: return 1
        # elif len(cl1) == 1: return 2

        mean_area1 = g1['area'].mean()
        mean_area2 = g2['area'].mean()

        compo_area = compo['area']
        if abs(compo_area - mean_area1) < abs(compo_area - mean_area2):
            return 1
        return 2

    def closer_cluster_by_mean_distance(self, compo_index, cluster1, cluster2):
        def min_distance(c, cl):
            return np.mean(np.square(abs(cl['center_row'] - c['center_row'])) + np.square(abs(cl['center_column'] - c['center_column'])))
        compos = self.compos_dataframe
        compo = compos.loc[compo_index]
        compos = compos[compos['id'] != compo['id']]
        cl1 = compos[compos[cluster1] == compo[cluster1]]
        cl2 = compos[compos[cluster2] == compo[cluster2]]
        if len(cl2) == 1: return 1
        elif len(cl1) == 1: return 2

        print(min_distance(compo, cl1), min_distance(compo, cl2))
        if min_distance(compo, cl1) < min_distance(compo, cl2):
            return 1
        return 2

    def check_group_of_two_compos_validity_by_areas(self):
        groups = self.compos_dataframe.groupby('group').groups
        for i in groups:
            # if the group only has two elements, check if it's valid by elements' areas
            if i != -1 and len(groups[i]) == 2:
                compos = self.compos_dataframe.loc[groups[i]]
                # if the two are too different in area, mark the group as invalid
                if compos['area'].max() > compos['area'].min() * 2:
                    self.compos_dataframe.loc[groups[i], 'group'] = -1

    def group_by_clusters_conflict(self, cluster, alignment, show=True, show_method='block'):
        compos = self.compos_dataframe
        group_id = compos['group'].max() + 1

        groups = self.compos_dataframe.groupby(cluster).groups
        for i in groups:
            if len(groups[i]) > 1:
                member_num = len(groups[i])
                for j in list(groups[i]):
                    if compos.loc[j, 'group'] == -1:
                        compos.loc[j, 'group'] = group_id
                        compos.loc[j, 'alignment'] = alignment
                    # conflict raises if a component can be grouped into multiple groups
                    # then double check it by the average area of the groups
                    else:
                        # keep in the previous group if the it is the only member in a new group
                        if member_num <= 1:
                            continue
                        # close to the current cluster
                        prev_group = compos[compos['group'] == compos.loc[j, 'group']]
                        if self.closer_group_by_mean_area(j, compos.loc[list(groups[i])], prev_group) == 1:
                            compos.loc[j, 'group'] = group_id
                            compos.loc[j, 'alignment'] = alignment
                        else:
                            member_num -= 1
                group_id += 1
        self.compos_dataframe['group'].astype(int)

        if show:
            name = cluster if type(cluster) != list else '+'.join(cluster)
            if show_method == 'line':
                self.visualize(gather_attr='group', name=name)
            elif show_method == 'block':
                self.visualize_fill(gather_attr='group', name=name)

    def select_by_class(self, categories, no_parent=False, replace=False):
        df = self.compos_dataframe
        df = df[df['class'].isin(categories)]
        if no_parent:
            df = df[pd.isna(df['parent'])]
        if replace:
            self.compos_dataframe = df
        else:
            return df

    def calc_gap_in_group(self):
        compos = self.compos_dataframe
        compos['gap'] = -1
        groups = compos.groupby('group').groups
        for i in groups:
            group = groups[i]
            if i != -1 and len(group) > 1:
                group_compos = compos.loc[list(groups[i])]
                alignment_in_group = group_compos.iloc[0]['alignment_in_group']
                if alignment_in_group == 'v':
                    group_compos = group_compos.sort_values('center_column')
                    for j in range(len(group_compos) - 1):
                        id = group_compos.iloc[j]['id']
                        compos.loc[id, 'gap'] = group_compos.iloc[j + 1]['row_min'] - group_compos.iloc[j]['row_max']
                else:
                    group_compos = group_compos.sort_values('center_row')
                    for j in range(len(group_compos) - 1):
                        id = group_compos.iloc[j]['id']
                        compos.loc[id, 'gap'] = group_compos.iloc[j + 1]['column_min'] - group_compos.iloc[j]['column_max']

    '''
    ******************************
    ******** Pair groups *********
    ******************************
    '''
    def pair_groups(self):
        # gather by same groups
        groups_nontext = self.split_groups('group_nontext')
        groups_text = self.split_groups('group_text')
        all_groups = groups_nontext + groups_text
        # all_groups = self.split_groups('group')

        # pairing between groups
        if 'group_pair' in self.compos_dataframe:
            start_pair_id = max(self.compos_dataframe['group_pair'])
        else:
            start_pair_id = 0
        pairs = pairing.pair_matching_within_groups(all_groups, start_pair_id)
        # merge the pairing result into the original dataframe
        df_all = self.compos_dataframe
        if pairs is not None:
            if 'group_pair' not in self.compos_dataframe:
                df_all = self.compos_dataframe.merge(pairs, how='left')
            else:
                df_all.loc[df_all[df_all['id'].isin(pairs['id'])]['id'], 'group_pair'] = pairs['group_pair']
                df_all.loc[df_all[df_all['id'].isin(pairs['id'])]['id'], 'pair_to'] = pairs['pair_to']
            # tidy up
            df_all = df_all.drop(columns=['group_nontext', 'group_text'])

            # add alignment between list items
            # df_all.rename({'alignment': 'alignment_list'}, axis=1, inplace=True)
            # df_all.loc[list(df_all[df_all['alignment_list'] == 'v']['id']), 'alignment_item'] = 'h'
            # df_all.loc[list(df_all[df_all['alignment_list'] == 'h']['id']), 'alignment_item'] = 'v'

            # fill nan and change type
            df_all = df_all.fillna(-1)
            # df_all[list(df_all.filter(like='group'))] = df_all[list(df_all.filter(like='group'))].astype(int)
            df_all['group_pair'] = df_all['group_pair'].astype(int)
            df_all['pair_to'] = df_all['pair_to'].astype(int)
        else:
            df_all['group_pair'] = -1
            df_all['pair_to'] = -1
        self.compos_dataframe = df_all

    def split_groups(self, group_name):
        compos = self.compos_dataframe
        groups = []
        g = compos.groupby(group_name).groups
        for i in g:
            if i == -1 or len(g[i]) <= 1:
                continue
            groups.append(compos.loc[g[i]])
        return groups

    '''
    ******************************
    ******* List Partition *******
    ******************************
    '''
    def list_item_partition(self):
        '''
        track paired compos' "pair_to" attr to assign "list_item" id
        '''
        if 'pair_to' not in self.compos_dataframe:
            return
        compos = self.compos_dataframe
        groups = compos.groupby("group_pair").groups
        listed_compos = pd.DataFrame()
        for i in groups:
            if i == -1:
                continue
            group = groups[i]
            paired_compos = self.compos_dataframe.loc[list(group)]
            self.gather_list_items(paired_compos)
            listed_compos = listed_compos.append(paired_compos)

        if len(listed_compos) > 0:
            self.compos_dataframe = self.compos_dataframe.merge(listed_compos, how='left')
            self.compos_dataframe['list_item'] = self.compos_dataframe['list_item'].fillna(-1).astype(int)
        else:
            self.compos_dataframe['list_item'] = -1

    def gather_list_items(self, compos):
        '''
            gather compos into a list item in the same row/column of a same pair(list)
            the reason for this is that some list contain more than 2 items, while the 'pair_to' attr only contains relation of two
        '''

        def search_list_item_by_compoid(compo_id):
            """
                list_items: dictionary => {id of first compo: ListItem}
            """
            for i in item_ids:
                if compo_id in item_ids[i]:
                    return i

        list_items = {}
        item_ids = {}
        mark = []
        for i in range(len(compos)):
            compo = compos.iloc[i]
            if compo['pair_to'] == -1:
                compos.loc[compo['id'], 'list_item'] = self.item_id
                self.item_id += 1
            # new item
            elif compo['id'] not in mark and compo['pair_to'] not in mark:
                compo_paired = compos.loc[compo['pair_to']]

                list_items[self.item_id] = [compo, compo_paired]
                item_ids[self.item_id] = [compo['id'], compo['pair_to']]

                compos.loc[compo['id'], 'list_item'] = self.item_id
                compos.loc[compo['pair_to'], 'list_item'] = self.item_id
                mark += [compo['id'], compo['pair_to']]
                self.item_id += 1

            elif compo['id'] in mark and compo['pair_to'] not in mark:
                index = search_list_item_by_compoid(compo['id'])
                list_items[index].append(compos.loc[compo['pair_to']])
                item_ids[index].append(compo['pair_to'])

                compos.loc[compo['pair_to'], 'list_item'] = index
                mark.append(compo['pair_to'])

            elif compo['id'] not in mark and compo['pair_to'] in mark:
                index = search_list_item_by_compoid(compo['pair_to'])
                list_items[index].append(compos.loc[compo['id']])
                item_ids[index].append(compo['id'])

                compos.loc[compo['id'], 'list_item'] = index
                mark.append(compo['id'])

        compos['list_item'] = compos['list_item'].astype(int)
        return list_items

    '''
    *****************************
    ******* Visualization *******
    *****************************
    '''
    def visualize(self, img=None, gather_attr='class', name='board'):
        if img is None:
            img = self.img.copy()
        draw.visualize(img, self.compos_dataframe, attr=gather_attr, name=name)

    def visualize_fill(self, img=None, gather_attr='class', name='board'):
        if img is None:
            img = self.img.copy()
        draw.visualize_fill(img, self.compos_dataframe, attr=gather_attr, name=name)
